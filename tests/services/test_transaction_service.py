from datetime import date
from unittest.mock import AsyncMock

import services.transaction_service as transaction_service


async def test_save_transactions_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.save_transactions.return_value = ["resultado-fake"]
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    result = await transaction_service.save_transactions(["transacao-fake"], 42)

    repository.save_transactions.assert_awaited_once_with(["transacao-fake"], 42)
    assert result == ["resultado-fake"]


async def test_get_transactions_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.find_by_user.return_value = ["transacao-fake"]
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    result = await transaction_service.get_transactions(42)

    repository.find_by_user.assert_awaited_once_with(42)
    assert result == ["transacao-fake"]


async def test_get_totals_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.get_totals_by_period.return_value = {"entradas": 1.0, "saidas": 2.0}
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    start, end = date(2026, 6, 1), date(2026, 6, 30)
    result = await transaction_service.get_totals(42, start, end)

    repository.get_totals_by_period.assert_awaited_once_with(42, start, end)
    assert result == {"entradas": 1.0, "saidas": 2.0}
