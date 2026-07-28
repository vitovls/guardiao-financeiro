from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import async_session
from database.entities.transaction import TransactionEntity
from models import Transacao
from repository.dedup import (
    SUSPECT_WINDOW_DAYS,
    compute_fingerprint,
    is_similar,
    normalize_description,
)
from repository.provider import TransactionRepository, TransactionSaveResult


def _to_transacao(e: TransactionEntity) -> Transacao:
    return Transacao(
        data=e.data, descricao=e.descricao, valor=e.valor, tipo=e.tipo, categoria=e.categoria
    )


class SqliteTransactionRepository(TransactionRepository):
    def __init__(self, session_factory=None):
        self._session_factory = session_factory or async_session

    async def save_transactions(
        self, transactions: list[Transacao], telegram_user_id: int
    ) -> list[TransactionSaveResult]:
        results = []
        async with self._session_factory() as session:
            for t in transactions:
                results.append(await self._save_one(session, t, telegram_user_id))
            await session.commit()
        return results

    async def _save_one(
        self, session: AsyncSession, t: Transacao, telegram_user_id: int
    ) -> TransactionSaveResult:
        descricao_norm = normalize_description(t.descricao)
        fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)

        same_day = await session.execute(
            select(TransactionEntity).where(
                TransactionEntity.telegram_user_id == telegram_user_id,
                TransactionEntity.data == t.data,
            )
        )
        for candidate in same_day.scalars().all():
            candidate_fp = compute_fingerprint(
                candidate.valor, candidate.tipo, normalize_description(candidate.descricao)
            )
            if candidate_fp == fingerprint:
                return TransactionSaveResult(transacao=t, status="duplicata_exata")

        window_start = t.data - timedelta(days=SUSPECT_WINDOW_DAYS)
        window_end = t.data + timedelta(days=SUSPECT_WINDOW_DAYS)
        window = await session.execute(
            select(TransactionEntity).where(
                TransactionEntity.telegram_user_id == telegram_user_id,
                TransactionEntity.data >= window_start,
                TransactionEntity.data <= window_end,
                TransactionEntity.valor == t.valor,
                TransactionEntity.tipo == t.tipo,
            )
        )
        similares = [
            _to_transacao(c)
            for c in window.scalars().all()
            if is_similar(normalize_description(c.descricao), descricao_norm)
        ]

        session.add(TransactionEntity(
            telegram_user_id=telegram_user_id,
            data=t.data, descricao=t.descricao, valor=t.valor, tipo=t.tipo, categoria=t.categoria,
        ))

        if similares:
            return TransactionSaveResult(transacao=t, status="suspeita", similares=similares)
        return TransactionSaveResult(transacao=t, status="nova")

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TransactionEntity).where(
                    TransactionEntity.telegram_user_id == telegram_user_id
                )
            )
            return [_to_transacao(e) for e in result.scalars().all()]

    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TransactionEntity.tipo, func.sum(TransactionEntity.valor))
                .where(
                    TransactionEntity.telegram_user_id == telegram_user_id,
                    TransactionEntity.data >= start,
                    TransactionEntity.data <= end,
                )
                .group_by(TransactionEntity.tipo)
            )
            key_map = {"entrada": "entradas", "saida": "saidas"}
            totals = {"entradas": 0.0, "saidas": 0.0}
            for tipo, total in result.all():
                key = key_map.get(tipo)
                if key:
                    totals[key] = total or 0.0
            return totals
