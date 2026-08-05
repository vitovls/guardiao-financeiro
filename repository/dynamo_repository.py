import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from models import Transacao
from repository.dedup import (
    SUSPECT_WINDOW_DAYS,
    compute_fingerprint,
    is_similar,
    normalize_description,
)
from repository.provider import (
    PendingConfirmation,
    RepositoryError,
    TransactionRepository,
    TransactionSaveResult,
)

_HIGH_SENTINEL = "￿"
_PROCESSADO_TTL_SECONDS = 24 * 60 * 60
_ESPECIAIS = ("CONFIG#", "PENDENTE#", "PROCESSADO#")


def _item_to_transacao(item: dict) -> Transacao:
    return Transacao(
        data=date.fromisoformat(item["data"]),
        descricao=item["descricao"],
        valor=float(item["valor"]),
        tipo=item["tipo"],
        categoria=item.get("categoria", ""),
    )


def _transacao_to_map(t: Transacao) -> dict:
    return {
        "data": t.data.isoformat(),
        "descricao": t.descricao,
        "valor": Decimal(str(t.valor)),
        "tipo": t.tipo,
        "categoria": t.categoria,
    }


def _criado_em_or_fallback(item: dict) -> datetime:
    raw = item.get("criadoEm")
    if raw:
        return datetime.fromisoformat(raw)
    return datetime.combine(date.fromisoformat(item["data"]), dt_time.min, tzinfo=timezone.utc)


def _item_to_pending(item: dict) -> PendingConfirmation:
    similar_raw = item.get("similarCriadoEm")
    return PendingConfirmation(
        id=item["sortKey"].removeprefix("PENDENTE#"),
        transacao=_item_to_transacao(item["transacao"]),
        motivo=item["motivo"],
        similares=[_item_to_transacao(s) for s in item.get("similares", [])],
        criado_em=datetime.fromisoformat(item["criadoEm"]),
        similar_criado_em=datetime.fromisoformat(similar_raw) if similar_raw else None,
    )


class DynamoTransactionRepository(TransactionRepository):
    def __init__(self, table_name: str, resource=None):
        self._table = (resource or boto3.resource("dynamodb", region_name="us-east-2")).Table(table_name)

    async def save_transactions(
        self, transactions: list[Transacao], telegram_user_id: int
    ) -> list[TransactionSaveResult]:
        criado_em = datetime.now(timezone.utc)
        return [await self._save_one(t, telegram_user_id, criado_em) for t in transactions]

    async def _save_one(
        self, t: Transacao, telegram_user_id: int, criado_em: datetime
    ) -> TransactionSaveResult:
        descricao_norm = normalize_description(t.descricao)
        fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)
        sort_key = f"{t.data.isoformat()}#{fingerprint}"
        user_id = str(telegram_user_id)

        exato = await self._find_exact(user_id, sort_key)
        if exato is not None:
            pendencia = await self._create_pending(user_id, t, "duplicata_exata", [exato], criado_em)
            return TransactionSaveResult(transacao=t, status="duplicata_exata", pendencia=pendencia)

        similares = await self._find_similar(user_id, t, descricao_norm, exclude_sort_key=sort_key)
        if similares:
            pendencia = await self._create_pending(user_id, t, "suspeita", similares, criado_em)
            return TransactionSaveResult(
                transacao=t, status="suspeita", similares=[s for s, _ in similares], pendencia=pendencia
            )

        item = {
            "userId": user_id,
            "sortKey": sort_key,
            "criadoEm": criado_em.isoformat(),
            **_transacao_to_map(t),
        }
        try:
            self._table.put_item(Item=item)
        except ClientError as exc:
            raise RepositoryError(f"falha ao gravar transação no DynamoDB: {exc}") from exc
        return TransactionSaveResult(transacao=t, status="nova")

    async def _find_exact(self, user_id: str, sort_key: str) -> tuple[Transacao, datetime] | None:
        try:
            response = self._table.get_item(Key={"userId": user_id, "sortKey": sort_key})
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar duplicata exata: {exc}") from exc
        item = response.get("Item")
        if not item:
            return None
        return _item_to_transacao(item), _criado_em_or_fallback(item)

    async def _find_similar(
        self, user_id: str, t: Transacao, descricao_norm: str, exclude_sort_key: str
    ) -> list[tuple[Transacao, datetime]]:
        start = (t.data - timedelta(days=SUSPECT_WINDOW_DAYS)).isoformat()
        end = (t.data + timedelta(days=SUSPECT_WINDOW_DAYS)).isoformat()
        try:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("userId").eq(user_id) & Key("sortKey").between(f"{start}#", f"{end}#{_HIGH_SENTINEL}")
                )
            )
            pendentes_response = self._table.query(
                KeyConditionExpression=Key("userId").eq(user_id) & Key("sortKey").begins_with("PENDENTE#"),
                FilterExpression=Attr("transacao.data").between(start, end),
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar candidatos de SUSPEITA: {exc}") from exc

        candidatos: list[tuple[str, Transacao, datetime]] = []
        for item in response.get("Items", []):
            if item["sortKey"] == exclude_sort_key:
                # o item recém-gravado por esta própria chamada já está visível na
                # Query (put_item já commitou antes de chegarmos aqui) — sem essa
                # exclusão, toda transação "nova" se compararia contra si mesma
                # (similaridade 1.0) e seria classificada como "suspeita".
                continue
            if float(item["valor"]) != t.valor or item["tipo"] != t.tipo:
                continue
            candidatos.append((item["descricao"], _item_to_transacao(item), _criado_em_or_fallback(item)))

        for pend_item in pendentes_response.get("Items", []):
            candidata = pend_item["transacao"]
            if float(candidata["valor"]) != t.valor or candidata["tipo"] != t.tipo:
                continue
            candidatos.append((
                candidata["descricao"],
                _item_to_transacao(candidata),
                datetime.fromisoformat(pend_item["criadoEm"]),
            ))

        return [
            (transacao, criado_em)
            for descricao, transacao, criado_em in candidatos
            if is_similar(normalize_description(descricao), descricao_norm)
        ]

    async def _create_pending(
        self,
        user_id: str,
        t: Transacao,
        motivo: str,
        similares: list[tuple[Transacao, datetime]],
        criado_em: datetime,
    ) -> PendingConfirmation:
        pendencia_id = uuid4().hex
        item = {
            "userId": user_id,
            "sortKey": f"PENDENTE#{pendencia_id}",
            "motivo": motivo,
            "transacao": _transacao_to_map(t),
            "similares": [_transacao_to_map(s) for s, _ in similares],
            "criadoEm": criado_em.isoformat(),
        }
        if similares:
            item["similarCriadoEm"] = similares[0][1].isoformat()
        try:
            self._table.put_item(Item=item)
        except ClientError as exc:
            raise RepositoryError(f"falha ao gravar pendência: {exc}") from exc
        return PendingConfirmation(
            id=pendencia_id,
            transacao=t,
            motivo=motivo,
            similares=[s for s, _ in similares],
            criado_em=criado_em,
            similar_criado_em=similares[0][1] if similares else None,
        )

    async def find_pending_by_user(self, telegram_user_id: int) -> list[PendingConfirmation]:
        user_id = str(telegram_user_id)
        try:
            response = self._table.query(
                KeyConditionExpression=Key("userId").eq(user_id) & Key("sortKey").begins_with("PENDENTE#")
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao listar pendências: {exc}") from exc
        return [_item_to_pending(item) for item in response.get("Items", [])]

    async def resolve_pending(self, telegram_user_id: int, pendencia_id: str, decisao: str) -> str:
        user_id = str(telegram_user_id)
        sort_key = f"PENDENTE#{pendencia_id}"
        try:
            response = self._table.get_item(Key={"userId": user_id, "sortKey": sort_key})
        except ClientError as exc:
            raise RepositoryError(f"falha ao ler pendência: {exc}") from exc
        item = response.get("Item")
        if not item:
            return "ja_resolvida"

        try:
            self._table.delete_item(
                Key={"userId": user_id, "sortKey": sort_key},
                ConditionExpression="attribute_exists(sortKey)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return "ja_resolvida"
            raise RepositoryError(f"falha ao remover pendência: {exc}") from exc

        if decisao == "nao":
            return "descartada"

        pendencia = _item_to_pending(item)
        t = pendencia.transacao
        fingerprint = compute_fingerprint(t.valor, t.tipo, normalize_description(t.descricao))
        final_sort_key = f"{t.data.isoformat()}#{fingerprint}#{pendencia_id}"
        final_item = {
            "userId": user_id,
            "sortKey": final_sort_key,
            "criadoEm": pendencia.criado_em.isoformat(),
            **_transacao_to_map(t),
        }
        try:
            self._table.put_item(Item=final_item)
        except ClientError as exc:
            raise RepositoryError(f"falha ao gravar transação confirmada: {exc}") from exc
        return "confirmada"

    async def try_claim_update(self, telegram_user_id: int, update_id: int) -> bool:
        user_id = str(telegram_user_id)
        expira_em = int(time.time()) + _PROCESSADO_TTL_SECONDS
        try:
            self._table.put_item(
                Item={"userId": user_id, "sortKey": f"PROCESSADO#{update_id}", "expiraEm": expira_em},
                ConditionExpression="attribute_not_exists(sortKey)",
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise RepositoryError(f"falha ao registrar idempotência de update: {exc}") from exc

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        try:
            response = self._table.query(KeyConditionExpression=Key("userId").eq(str(telegram_user_id)))
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar transações do usuário: {exc}") from exc
        return [
            _item_to_transacao(item)
            for item in response.get("Items", [])
            if not item["sortKey"].startswith(_ESPECIAIS)
        ]

    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date, categoria: str | None = None
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

        categoria_norm = normalize_description(categoria) if categoria else None
        totals = {"entradas": 0.0, "saidas": 0.0}
        key_map = {"entrada": "entradas", "saida": "saidas"}
        for item in response.get("Items", []):
            if item["sortKey"].startswith(_ESPECIAIS):
                continue
            if categoria_norm and normalize_description(item.get("categoria", "")) != categoria_norm:
                continue
            key = key_map.get(item.get("tipo"))
            if key:
                totals[key] += float(item["valor"])
        return totals
