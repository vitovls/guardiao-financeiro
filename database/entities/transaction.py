from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base


class TransactionEntity(Base):
    __tablename__ = "transacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, index=True)

    data: Mapped[date] = mapped_column(Date)
    descricao: Mapped[str] = mapped_column(String)
    valor: Mapped[float] = mapped_column(Float)
    tipo: Mapped[str] = mapped_column(String)
    categoria: Mapped[str] = mapped_column(String, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
