from database.connection import async_session
from models import Transacao
from repository.transaction import TransactionRepository


async def save_transactions(transactions: list[Transacao], telegram_user_id: int) -> None:
    async with async_session() as session:
        repository = TransactionRepository(session)
        await repository.save_transactions(transactions, telegram_user_id)


async def get_transactions(telegram_user_id: int) -> list[Transacao]:
    async with async_session() as session:
        repository = TransactionRepository(session)
        return await repository.find_by_user(telegram_user_id)
