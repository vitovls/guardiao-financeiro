from datetime import date

from models import Transacao
from repository.factory import get_transaction_repository
from repository.provider import TransactionSaveResult


async def save_transactions(transactions: list[Transacao], telegram_user_id: int) -> list[TransactionSaveResult]:
    repository = get_transaction_repository()
    return await repository.save_transactions(transactions, telegram_user_id)


async def get_transactions(telegram_user_id: int) -> list[Transacao]:
    repository = get_transaction_repository()
    return await repository.find_by_user(telegram_user_id)


async def get_totals(telegram_user_id: int, start: date, end: date) -> dict[str, float]:
    repository = get_transaction_repository()
    return await repository.get_totals_by_period(telegram_user_id, start, end)
