from database.connection import async_session
from models import Transacao
from repository.transacao import TransacaoRepository


async def salvar_transacoes(transacoes: list[Transacao], usuario_telegram_id: int) -> None:
    async with async_session() as session:
        repositorio = TransacaoRepository(session)
        await repositorio.salvar_transacoes(transacoes, usuario_telegram_id)


async def buscar_transacoes(usuario_telegram_id: int) -> list[Transacao]:
    async with async_session() as session:
        repositorio = TransacaoRepository(session)
        return await repositorio.buscar_por_usuario(usuario_telegram_id)
