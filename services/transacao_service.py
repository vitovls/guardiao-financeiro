from database.connection import async_session
from models import Transacao
from repository.transacao import TransacaoRepository


async def salvar_transacoes(transacoes: list[Transacao], usuario_telegram_id: int) -> None:
    async with async_session() as session:
        repo = TransacaoRepository(session)
        for transacao in transacoes:
            await repo.salvar(transacao, usuario_telegram_id)


async def buscar_transacoes(usuario_telegram_id: int) -> list[Transacao]:
    async with async_session() as session:
        repo = TransacaoRepository(session)
        return await repo.buscar_por_usuario(usuario_telegram_id)
