from datetime import date
from unittest.mock import Mock

import pytest
from botocore.exceptions import ClientError

from models import Transacao
from repository.dedup import compute_fingerprint, normalize_description
from repository.dynamo_repository import _HIGH_SENTINEL, DynamoTransactionRepository
from repository.provider import RepositoryError


def _transacao(data=date(2026, 6, 15), descricao="cafe", valor=8.0, tipo="saida", categoria="alimentacao"):
    return Transacao(data=data, descricao=descricao, valor=valor, tipo=tipo, categoria=categoria)


def _condition_check_failed() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "item already exists"}}, "PutItem"
    )


def _sort_key(t: Transacao) -> str:
    fingerprint = compute_fingerprint(t.valor, t.tipo, normalize_description(t.descricao))
    return f"{t.data.isoformat()}#{fingerprint}"


def _item(t: Transacao, sort_key: str | None = None) -> dict:
    return {
        "userId": "1",
        "sortKey": sort_key or _sort_key(t),
        "data": t.data.isoformat(),
        "descricao": t.descricao,
        "valor": t.valor,
        "tipo": t.tipo,
        "categoria": t.categoria,
    }


async def test_save_transaction_with_categoria_includes_attribute_in_item():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao(categoria="alimentacao")
    table.query.return_value = {"Items": []}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    await repo.save_transactions([t], 1)

    item = table.put_item.call_args.kwargs["Item"]
    assert item["categoria"] == "alimentacao"


async def test_save_new_transaction_excludes_itself_from_suspeita_check():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    table.query.return_value = {"Items": [_item(t)]}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    results = await repo.save_transactions([t], 1)

    assert results[0].status == "nova"
    table.put_item.assert_called_once()


async def test_put_item_condition_failure_is_duplicata_exata_and_skips_query():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    table.put_item.side_effect = _condition_check_failed()

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    results = await repo.save_transactions([_transacao()], 1)

    assert results[0].status == "duplicata_exata"
    table.query.assert_not_called()


async def test_save_transaction_with_similar_candidate_is_suspeita():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao(descricao="supermercado extra")
    similar = _transacao(descricao="supermercado extra ltda")

    table.query.return_value = {"Items": [_item(t), _item(similar)]}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    results = await repo.save_transactions([t], 1)

    assert results[0].status == "suspeita"
    assert len(results[0].similares) == 1
    assert results[0].similares[0].descricao == "supermercado extra ltda"


async def test_put_item_other_error_raises_repository_error():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    table.put_item.side_effect = ClientError(
        {"Error": {"Code": "ValidationException", "Message": "bad request"}}, "PutItem"
    )

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)

    with pytest.raises(RepositoryError):
        await repo.save_transactions([_transacao()], 1)


async def test_cafe_bolo_cafe_same_day_second_cafe_is_duplicata_exata():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table

    cafe = _transacao(descricao="cafe", valor=8.0)
    bolo = _transacao(descricao="bolo", valor=10.0)

    table.put_item.side_effect = [None, None, _condition_check_failed()]
    table.query.side_effect = [
        {"Items": [_item(cafe)]},
        {"Items": [_item(bolo)]},
    ]

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)

    first = await repo.save_transactions([cafe], 1)
    middle = await repo.save_transactions([bolo], 1)
    last = await repo.save_transactions([cafe], 1)

    assert first[0].status == "nova"
    assert middle[0].status == "nova"
    assert last[0].status == "duplicata_exata"
    assert table.query.call_count == 2


async def test_find_by_user_filters_config_items():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    table.query.return_value = {
        "Items": [_item(t), {"userId": "1", "sortKey": "CONFIG#lazer", "nome": "lazer"}]
    }

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    result = await repo.find_by_user(1)

    assert len(result) == 1
    assert result[0].descricao == "cafe"
    call_kwargs = table.query.call_args.kwargs
    assert "KeyConditionExpression" in call_kwargs


async def test_get_totals_by_period_sums_excludes_config_and_uses_sentinel():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    table.query.return_value = {
        "Items": [
            {"sortKey": "2026-06-10#aaa", "tipo": "entrada", "valor": 1000.0},
            {"sortKey": "2026-06-15#bbb", "tipo": "saida", "valor": 300.0},
            {"sortKey": "CONFIG#lazer", "tipo": "config", "valor": 0},
        ]
    }

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 1000.0, "saidas": 300.0}

    key_condition = table.query.call_args.kwargs["KeyConditionExpression"]
    _, between_condition = key_condition._values
    _, low, high = between_condition._values
    assert low == "2026-06-01#"
    assert high == f"2026-06-30#{_HIGH_SENTINEL}"
