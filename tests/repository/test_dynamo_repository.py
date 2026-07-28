from datetime import date, datetime
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
    table.get_item.return_value = {}
    table.query.return_value = {"Items": []}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    await repo.save_transactions([t], 1)

    item = table.put_item.call_args.kwargs["Item"]
    assert item["categoria"] == "alimentacao"


async def test_save_new_transaction_excludes_itself_from_suspeita_check():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    table.get_item.return_value = {}
    table.query.side_effect = [{"Items": [_item(t)]}, {"Items": []}]

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    results = await repo.save_transactions([t], 1)

    assert results[0].status == "nova"
    table.put_item.assert_called_once()


async def test_exact_match_creates_pending_confirmation_instead_of_blocking():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    table.get_item.return_value = {"Item": _item(t)}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    results = await repo.save_transactions([t], 1)

    assert results[0].status == "duplicata_exata"
    assert results[0].pendencia is not None
    assert results[0].pendencia.motivo == "duplicata_exata"
    table.query.assert_not_called()
    table.put_item.assert_called_once()
    put_item_call = table.put_item.call_args.kwargs["Item"]
    assert put_item_call["sortKey"].startswith("PENDENTE#")


async def test_save_transaction_with_similar_candidate_is_suspeita():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao(descricao="supermercado extra")
    similar = _transacao(descricao="supermercado extra ltda")

    table.get_item.return_value = {}
    table.query.side_effect = [{"Items": [_item(t), _item(similar)]}, {"Items": []}]

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    results = await repo.save_transactions([t], 1)

    assert results[0].status == "suspeita"
    assert results[0].pendencia is not None
    assert results[0].pendencia.motivo == "suspeita"
    assert len(results[0].pendencia.similares) == 1
    assert results[0].pendencia.similares[0].descricao == "supermercado extra ltda"
    put_item_call = table.put_item.call_args.kwargs["Item"]
    assert put_item_call["sortKey"].startswith("PENDENTE#")


async def test_put_item_other_error_raises_repository_error():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    table.get_item.return_value = {}
    table.query.return_value = {"Items": []}
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

    table.get_item.side_effect = [{}, {}, {"Item": _item(cafe)}]
    table.query.side_effect = [
        {"Items": [_item(cafe)]},
        {"Items": []},
        {"Items": [_item(bolo)]},
        {"Items": []},
    ]

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)

    first = await repo.save_transactions([cafe], 1)
    middle = await repo.save_transactions([bolo], 1)
    last = await repo.save_transactions([cafe], 1)

    assert first[0].status == "nova"
    assert middle[0].status == "nova"
    assert last[0].status == "duplicata_exata"
    assert last[0].pendencia is not None
    assert table.query.call_count == 4


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


def _pend_item(
    pendencia_id: str,
    t: Transacao,
    motivo: str,
    criado_em: str = "2026-06-15T10:00:00",
    similares: list[Transacao] | None = None,
    similar_criado_em: str | None = None,
) -> dict:
    item = {
        "userId": "1",
        "sortKey": f"PENDENTE#{pendencia_id}",
        "motivo": motivo,
        "transacao": {
            "data": t.data.isoformat(),
            "descricao": t.descricao,
            "valor": t.valor,
            "tipo": t.tipo,
            "categoria": t.categoria,
        },
        "similares": [
            {
                "data": s.data.isoformat(),
                "descricao": s.descricao,
                "valor": s.valor,
                "tipo": s.tipo,
                "categoria": s.categoria,
            }
            for s in (similares or [])
        ],
        "criadoEm": criado_em,
    }
    if similar_criado_em:
        item["similarCriadoEm"] = similar_criado_em
    return item


async def test_find_similar_includes_pending_items_from_same_user():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao(descricao="mercado")
    pend_t = _transacao(descricao="mercado")
    table.get_item.return_value = {}
    table.query.side_effect = [
        {"Items": []},
        {"Items": [_pend_item("xyz", pend_t, "suspeita")]},
    ]

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    results = await repo.save_transactions([t], 1)

    assert results[0].status == "suspeita"
    assert results[0].pendencia.similares[0].descricao == "mercado"


async def test_resolve_pending_sim_writes_transaction_with_suffixed_sort_key_and_deletes_pending():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    pendencia_id = "abc123"
    table.get_item.return_value = {"Item": _pend_item(pendencia_id, t, "suspeita")}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    resultado = await repo.resolve_pending(1, pendencia_id, "sim")

    assert resultado == "confirmada"
    table.delete_item.assert_called_once()
    delete_kwargs = table.delete_item.call_args.kwargs
    assert delete_kwargs["ConditionExpression"] == "attribute_exists(sortKey)"
    put_item_kwargs = table.put_item.call_args.kwargs
    assert put_item_kwargs["Item"]["sortKey"].endswith(f"#{pendencia_id}")
    assert "ConditionExpression" not in put_item_kwargs


async def test_resolve_pending_nao_deletes_without_writing_transaction():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    pendencia_id = "abc123"
    table.get_item.return_value = {"Item": _pend_item(pendencia_id, t, "suspeita")}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    resultado = await repo.resolve_pending(1, pendencia_id, "nao")

    assert resultado == "descartada"
    table.delete_item.assert_called_once()
    table.put_item.assert_not_called()


async def test_resolve_pending_already_resolved_returns_ja_resolvida_without_deleting_or_writing():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    table.get_item.return_value = {}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    resultado = await repo.resolve_pending(1, "abc123", "sim")

    assert resultado == "ja_resolvida"
    table.delete_item.assert_not_called()
    table.put_item.assert_not_called()


async def test_resolve_pending_double_tap_race_returns_ja_resolvida():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    table.get_item.return_value = {"Item": _pend_item("abc123", t, "suspeita")}
    table.delete_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "gone"}}, "DeleteItem"
    )

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    resultado = await repo.resolve_pending(1, "abc123", "sim")

    assert resultado == "ja_resolvida"
    table.put_item.assert_not_called()


async def test_find_pending_by_user_queries_with_begins_with_pendente():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    table.query.return_value = {"Items": [_pend_item("abc123", t, "suspeita")]}

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    result = await repo.find_pending_by_user(1)

    assert len(result) == 1
    assert result[0].id == "abc123"


async def test_try_claim_update_first_time_returns_true():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    result = await repo.try_claim_update(1, 999)

    assert result is True
    table.put_item.assert_called_once()


async def test_try_claim_update_already_processed_returns_false():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    table.put_item.side_effect = ClientError(
        {"Error": {"Code": "ConditionalCheckFailedException", "Message": "already processed"}}, "PutItem"
    )

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    result = await repo.try_claim_update(1, 999)

    assert result is False


async def test_find_by_user_excludes_pending_and_processado_items():
    resource, table = Mock(), Mock()
    resource.Table.return_value = table
    t = _transacao()
    table.query.return_value = {
        "Items": [
            _item(t),
            {"userId": "1", "sortKey": "CONFIG#lazer", "nome": "lazer"},
            {"userId": "1", "sortKey": "PENDENTE#abc123"},
            {"userId": "1", "sortKey": "PROCESSADO#999"},
        ]
    }

    repo = DynamoTransactionRepository(table_name="tbl", resource=resource)
    result = await repo.find_by_user(1)

    assert len(result) == 1
    assert result[0].descricao == "cafe"
