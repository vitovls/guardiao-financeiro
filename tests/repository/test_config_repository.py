from datetime import date, datetime
from unittest.mock import Mock

from repository.config_repository import ConfigRepository


async def test_save_config_mensal_has_no_data_limite():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table

    repo = ConfigRepository(table_name="tbl", resource=resource)
    await repo.save_config(telegram_user_id=1, nome="lazer", teto=300.0, periodo="mensal")

    item = table.put_item.call_args.kwargs["Item"]
    assert item["periodo"] == "mensal"
    assert "dataLimite" not in item


async def test_save_config_unico_includes_data_limite():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table

    repo = ConfigRepository(table_name="tbl", resource=resource)
    await repo.save_config(
        telegram_user_id=1,
        nome="cartao",
        teto=2000.0,
        periodo="unico",
        data_limite=date(2026, 12, 31),
    )

    item = table.put_item.call_args.kwargs["Item"]
    assert item["dataLimite"] == "2026-12-31"


async def test_get_config_returns_none_when_item_missing():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    table.get_item.return_value = {}

    repo = ConfigRepository(table_name="tbl", resource=resource)
    result = await repo.get_config(telegram_user_id=1, nome="lazer")

    assert result is None


async def test_get_config_returns_config_item_with_float_teto():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    now = datetime(2026, 1, 1, 12, 0, 0).isoformat()
    table.get_item.return_value = {
        "Item": {
            "nome": "lazer",
            "teto": 300,
            "periodo": "mensal",
            "rollover": False,
            "createdAt": now,
            "updatedAt": now,
        }
    }

    repo = ConfigRepository(table_name="tbl", resource=resource)
    result = await repo.get_config(telegram_user_id=1, nome="lazer")

    assert result.teto == 300.0
    assert isinstance(result.teto, float)


async def test_list_configs_queries_with_begins_with_config():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    table.query.return_value = {"Items": []}

    repo = ConfigRepository(table_name="tbl", resource=resource)
    await repo.list_configs(telegram_user_id=1)

    key_condition = table.query.call_args.kwargs["KeyConditionExpression"]
    _, begins_with_condition = key_condition._values
    assert begins_with_condition._values[1] == "CONFIG#"
