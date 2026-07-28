from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from models import Transacao


class RepositoryError(Exception):
    """Erro genérico de repository, tratado pelos services (nunca vaza driver nativo)."""


class TransactionSaveResult(BaseModel):
    transacao: Transacao
    status: Literal["nova", "suspeita", "duplicata_exata"]
    similares: list[Transacao] = []


class ConfigItem(BaseModel):
    nome: str
    teto: float
    periodo: Literal["mensal", "unico"]
    rollover: bool = False
    data_limite: date | None = None
    created_at: datetime
    updated_at: datetime


class TransactionRepository(ABC):
    @abstractmethod
    async def save_transactions(
        self, transactions: list[Transacao], telegram_user_id: int
    ) -> list[TransactionSaveResult]: ...

    @abstractmethod
    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]: ...

    @abstractmethod
    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]: ...
