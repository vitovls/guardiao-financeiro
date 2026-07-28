from datetime import date
from unittest.mock import AsyncMock

import scripts.migrate_sqlite_to_dynamo as migrate_script
from database.entities.transaction import TransactionEntity
from repository.provider import TransactionSaveResult


async def _seed(session_factory, count, telegram_user_id=1):
    async with session_factory() as session:
        for i in range(count):
            session.add(TransactionEntity(
                telegram_user_id=telegram_user_id,
                data=date(2026, 6, 1),
                descricao=f"transacao {i}",
                valor=10.0 + i,
                tipo="saida",
                categoria="",
            ))
        await session.commit()


async def test_migrate_reports_equal_read_and_written_counts_when_all_new(
    monkeypatch, session_factory, capsys
):
    n = 3
    await _seed(session_factory, n)
    monkeypatch.setattr(migrate_script, "async_session", session_factory)

    fake_repo = AsyncMock()

    def always_nova(transactions, telegram_user_id):
        return [TransactionSaveResult(transacao=transactions[0], status="nova")]

    fake_repo.save_transactions.side_effect = always_nova
    monkeypatch.setattr(migrate_script, "DynamoTransactionRepository", lambda table_name: fake_repo)

    await migrate_script.migrate()

    captured = capsys.readouterr()
    assert f"Linhas lidas do SQLite: {n}" in captured.out
    assert f"Items gravados no DynamoDB: {n}" in captured.out


async def test_migrate_reports_written_count_minus_duplicates_and_lists_difference(
    monkeypatch, session_factory, capsys
):
    n = 3
    await _seed(session_factory, n)
    monkeypatch.setattr(migrate_script, "async_session", session_factory)

    call_count = {"n": 0}

    def second_call_is_duplicate(transactions, telegram_user_id):
        call_count["n"] += 1
        status = "duplicata_exata" if call_count["n"] == 2 else "nova"
        return [TransactionSaveResult(transacao=transactions[0], status=status)]

    fake_repo = AsyncMock()
    fake_repo.save_transactions.side_effect = second_call_is_duplicate
    monkeypatch.setattr(migrate_script, "DynamoTransactionRepository", lambda table_name: fake_repo)

    await migrate_script.migrate()

    captured = capsys.readouterr()
    assert f"Linhas lidas do SQLite: {n}" in captured.out
    assert f"Items gravados no DynamoDB: {n - 1}" in captured.out
    assert "Diferença: 1 linha(s)" in captured.out
