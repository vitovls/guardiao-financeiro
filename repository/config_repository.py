from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from repository.provider import ConfigItem, RepositoryError


def _item_to_config(item: dict) -> ConfigItem:
    return ConfigItem(
        nome=item["nome"],
        teto=float(item["teto"]),
        periodo=item["periodo"],
        rollover=item.get("rollover", False),
        data_limite=date.fromisoformat(item["dataLimite"]) if item.get("dataLimite") else None,
        created_at=datetime.fromisoformat(item["createdAt"]),
        updated_at=datetime.fromisoformat(item["updatedAt"]),
    )


class ConfigRepository:
    def __init__(self, table_name: str, resource=None):
        self._table = (resource or boto3.resource("dynamodb", region_name="us-east-2")).Table(table_name)

    async def save_config(
        self,
        telegram_user_id: int,
        nome: str,
        teto: float,
        periodo: Literal["mensal", "unico"],
        rollover: bool = False,
        data_limite: date | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        item = {
            "userId": str(telegram_user_id),
            "sortKey": f"CONFIG#{nome.lower()}",
            "nome": nome,
            "teto": Decimal(str(teto)),
            "periodo": periodo,
            "rollover": rollover,
            "createdAt": now,
            "updatedAt": now,
        }
        if data_limite:
            item["dataLimite"] = data_limite.isoformat()
        try:
            self._table.put_item(Item=item)
        except ClientError as exc:
            raise RepositoryError(f"falha ao gravar configuração: {exc}") from exc

    async def get_config(self, telegram_user_id: int, nome: str) -> ConfigItem | None:
        try:
            response = self._table.get_item(
                Key={"userId": str(telegram_user_id), "sortKey": f"CONFIG#{nome.lower()}"}
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao ler configuração: {exc}") from exc
        item = response.get("Item")
        return _item_to_config(item) if item else None

    async def list_configs(self, telegram_user_id: int) -> list[ConfigItem]:
        try:
            response = self._table.query(
                KeyConditionExpression=Key("userId").eq(str(telegram_user_id))
                & Key("sortKey").begins_with("CONFIG#")
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao listar configurações: {exc}") from exc
        return [_item_to_config(item) for item in response.get("Items", [])]
