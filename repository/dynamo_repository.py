from datetime import date, timedelta
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from models import Transacao
from repository.dedup import (
    SUSPECT_WINDOW_DAYS,
    compute_fingerprint,
    is_similar,
    normalize_description,
)
from repository.provider import RepositoryError, TransactionRepository, TransactionSaveResult

_HIGH_SENTINEL = "￿"


def _item_to_transacao(item: dict) -> Transacao:
    return Transacao(
        data=date.fromisoformat(item["data"]),
        descricao=item["descricao"],
        valor=float(item["valor"]),
        tipo=item["tipo"],
        categoria=item.get("categoria", ""),
    )


class DynamoTransactionRepository(TransactionRepository):
    def __init__(self, table_name: str, resource=None):
        self._table = (resource or boto3.resource("dynamodb", region_name="us-east-2")).Table(table_name)

    async def save_transactions(
        self, transactions: list[Transacao], telegram_user_id: int
    ) -> list[TransactionSaveResult]:
        return [await self._save_one(t, telegram_user_id) for t in transactions]

    async def _save_one(self, t: Transacao, telegram_user_id: int) -> TransactionSaveResult:
        descricao_norm = normalize_description(t.descricao)
        fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)
        sort_key = f"{t.data.isoformat()}#{fingerprint}"
        user_id = str(telegram_user_id)

        item = {
            "userId": user_id,
            "sortKey": sort_key,
            "data": t.data.isoformat(),
            "descricao": t.descricao,
            "valor": Decimal(str(t.valor)),
            "tipo": t.tipo,
        }
        if t.categoria:
            item["categoria"] = t.categoria
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(sortKey)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return TransactionSaveResult(transacao=t, status="duplicata_exata")
            raise RepositoryError(f"falha ao gravar transação no DynamoDB: {exc}") from exc

        similares = await self._find_similar(user_id, t, descricao_norm, exclude_sort_key=sort_key)
        if similares:
            return TransactionSaveResult(transacao=t, status="suspeita", similares=similares)
        return TransactionSaveResult(transacao=t, status="nova")

    async def _find_similar(
        self, user_id: str, t: Transacao, descricao_norm: str, exclude_sort_key: str
    ) -> list[Transacao]:
        start = (t.data - timedelta(days=SUSPECT_WINDOW_DAYS)).isoformat()
        end = (t.data + timedelta(days=SUSPECT_WINDOW_DAYS)).isoformat()
        try:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("userId").eq(user_id) & Key("sortKey").between(f"{start}#", f"{end}#{_HIGH_SENTINEL}")
                )
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar candidatos de SUSPEITA: {exc}") from exc

        similares = []
        for item in response.get("Items", []):
            if item["sortKey"] == exclude_sort_key:
                # o item recém-gravado por esta própria chamada já está visível na
                # Query (put_item já commitou antes de chegarmos aqui) — sem essa
                # exclusão, toda transação "nova" se compararia contra si mesma
                # (similaridade 1.0) e seria classificada como "suspeita".
                continue
            if float(item["valor"]) != t.valor or item["tipo"] != t.tipo:
                continue
            if is_similar(normalize_description(item["descricao"]), descricao_norm):
                similares.append(_item_to_transacao(item))
        return similares

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        try:
            response = self._table.query(KeyConditionExpression=Key("userId").eq(str(telegram_user_id)))
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar transações do usuário: {exc}") from exc
        return [
            _item_to_transacao(item)
            for item in response.get("Items", [])
            if not item["sortKey"].startswith("CONFIG#")
        ]

    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]:
        try:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("userId").eq(str(telegram_user_id))
                    & Key("sortKey").between(f"{start.isoformat()}#", f"{end.isoformat()}#{_HIGH_SENTINEL}")
                )
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar totais por período: {exc}") from exc

        totals = {"entradas": 0.0, "saidas": 0.0}
        key_map = {"entrada": "entradas", "saida": "saidas"}
        for item in response.get("Items", []):
            if item["sortKey"].startswith("CONFIG#"):
                continue
            key = key_map.get(item.get("tipo"))
            if key:
                totals[key] += float(item["valor"])
        return totals
