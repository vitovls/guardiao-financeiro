from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.entities.transacao import TransacaoEntity
from models import Transacao


class TransacaoRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def salvar(self, transacao: Transacao, usuario_telegram_id: int) -> None:
        entity = TransacaoEntity(
            usuario_telegram_id=usuario_telegram_id,
            data=transacao.data,
            descricao=transacao.descricao,
            valor=transacao.valor,
            tipo=transacao.tipo,
            categoria=transacao.categoria,
        )
        self.session.add(entity)
        await self.session.commit()

    async def buscar_por_usuario(self, usuario_telegram_id: int) -> list[Transacao]:
        result = await self.session.execute(
            select(TransacaoEntity).where(
                TransacaoEntity.usuario_telegram_id == usuario_telegram_id
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
