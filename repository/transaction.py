from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.entities.transaction import TransactionEntity
from models import Transacao


class TransactionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_transactions(self, transactions: list[Transacao], telegram_user_id: int) -> None:
        for transaction in transactions:
            self.session.add(TransactionEntity(
                telegram_user_id=telegram_user_id,
                data=transaction.data,
                descricao=transaction.descricao,
                valor=transaction.valor,
                tipo=transaction.tipo,
                categoria=transaction.categoria,
            ))
        await self.session.commit()

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        result = await self.session.execute(
            select(TransactionEntity).where(
                TransactionEntity.telegram_user_id == telegram_user_id
            )
        )
        entities = result.scalars().all()
        return [
            Transacao(
                data=e.data,
                descricao=e.descricao,
                valor=e.valor,
                tipo=e.tipo,
                categoria=e.categoria,
            )
            for e in entities
        ]
