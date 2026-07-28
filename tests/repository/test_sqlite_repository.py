from datetime import date

from repository.sqlite_repository import SqliteTransactionRepository
from models import Transacao


def _transacao(data=date(2026, 6, 15), descricao="cafe padaria", valor=8.0, tipo="saida", categoria="alimentacao"):
    return Transacao(data=data, descricao=descricao, valor=valor, tipo=tipo, categoria=categoria)


async def test_identical_transaction_inserted_twice_is_duplicata_exata_and_not_duplicated(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    first = await repo.save_transactions([_transacao()], 1)
    second = await repo.save_transactions([_transacao()], 1)

    assert first[0].status == "nova"
    assert second[0].status == "duplicata_exata"

    stored = await repo.find_by_user(1)
    assert len(stored) == 1


async def test_similar_description_within_window_is_suspeita_and_both_are_kept(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    await repo.save_transactions([_transacao(descricao="supermercado extra")], 1)
    second = await repo.save_transactions([_transacao(descricao="supermercado extra ltda")], 1)

    assert second[0].status == "suspeita"
    assert len(second[0].similares) == 1
    assert second[0].similares[0].descricao == "supermercado extra"

    stored = await repo.find_by_user(1)
    assert len(stored) == 2


async def test_transaction_without_nearby_candidate_is_nova(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    result = await repo.save_transactions([_transacao()], 1)

    assert result[0].status == "nova"


async def test_cafe_bolo_cafe_same_day_second_cafe_is_duplicata_exata(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    cafe = _transacao(descricao="cafe", valor=8.0)
    bolo = _transacao(descricao="bolo", valor=10.0)

    first = await repo.save_transactions([cafe], 1)
    middle = await repo.save_transactions([bolo], 1)
    last = await repo.save_transactions([cafe], 1)

    assert first[0].status == "nova"
    assert middle[0].status == "nova"
    assert last[0].status == "duplicata_exata"


async def test_get_totals_sums_entradas_and_saidas(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    await repo.save_transactions([_transacao(tipo="entrada", valor=1000.0, data=date(2026, 6, 10), descricao="salario")], 1)
    await repo.save_transactions([_transacao(tipo="saida", valor=300.0, data=date(2026, 6, 15), descricao="mercado")], 1)
    await repo.save_transactions([_transacao(tipo="saida", valor=150.0, data=date(2026, 6, 20), descricao="farmacia")], 1)

    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 1000.0, "saidas": 450.0}


async def test_get_totals_ignores_other_users(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    await repo.save_transactions([_transacao(tipo="entrada", valor=500.0, data=date(2026, 6, 10), descricao="salario")], 1)
    await repo.save_transactions([_transacao(tipo="entrada", valor=9999.0, data=date(2026, 6, 10), descricao="salario")], 2)

    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 500.0, "saidas": 0.0}


async def test_get_totals_ignores_transactions_outside_range(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    await repo.save_transactions([_transacao(tipo="saida", valor=200.0, data=date(2026, 5, 31), descricao="a")], 1)
    await repo.save_transactions([_transacao(tipo="saida", valor=100.0, data=date(2026, 6, 15), descricao="b")], 1)
    await repo.save_transactions([_transacao(tipo="saida", valor=300.0, data=date(2026, 7, 1), descricao="c")], 1)

    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 0.0, "saidas": 100.0}


async def test_get_totals_returns_zeros_when_no_transactions(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 0.0, "saidas": 0.0}


async def test_find_by_user_returns_stored_transactions(session_factory):
    repo = SqliteTransactionRepository(session_factory)

    await repo.save_transactions([_transacao()], 1)

    stored = await repo.find_by_user(1)

    assert len(stored) == 1
    assert stored[0].descricao == "cafe padaria"
