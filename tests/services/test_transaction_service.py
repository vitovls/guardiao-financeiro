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


async def test_get_pending_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.find_pending_by_user.return_value = ["pendencia-fake"]
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    result = await transaction_service.get_pending(42)

    repository.find_pending_by_user.assert_awaited_once_with(42)
    assert result == ["pendencia-fake"]


async def test_resolve_pending_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.resolve_pending.return_value = "confirmada"
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    result = await transaction_service.resolve_pending(42, "abc123", "sim")

    repository.resolve_pending.assert_awaited_once_with(42, "abc123", "sim")
    assert result == "confirmada"


async def test_claim_update_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.try_claim_update.return_value = True
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    result = await transaction_service.claim_update(42, 999)

    repository.try_claim_update.assert_awaited_once_with(42, 999)
    assert result is True
