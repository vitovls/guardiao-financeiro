from datetime import date

from models import Transacao
from repository.factory import get_transaction_repository
from repository.provider import PendingConfirmation, TransactionSaveResult


async def save_transactions(transactions: list[Transacao], telegram_user_id: int) -> list[TransactionSaveResult]:
    repository = get_transaction_repository()
    return await repository.save_transactions(transactions, telegram_user_id)


async def get_transactions(telegram_user_id: int) -> list[Transacao]:
    repository = get_transaction_repository()
    return await repository.find_by_user(telegram_user_id)


async def get_totals(
    telegram_user_id: int, start: date, end: date, categoria: str | None = None
) -> dict[str, float]:
    repository = get_transaction_repository()
    return await repository.get_totals_by_period(telegram_user_id, start, end, categoria)


async def get_pending(telegram_user_id: int) -> list[PendingConfirmation]:
    repository = get_transaction_repository()
    return await repository.find_pending_by_user(telegram_user_id)


async def resolve_pending(telegram_user_id: int, pendencia_id: str, decisao: str) -> str:
    repository = get_transaction_repository()
    return await repository.resolve_pending(telegram_user_id, pendencia_id, decisao)


async def claim_update(telegram_user_id: int, update_id: int) -> bool:
    repository = get_transaction_repository()
    return await repository.try_claim_update(telegram_user_id, update_id)
