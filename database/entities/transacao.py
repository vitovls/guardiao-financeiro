from datetime import datetime

from sqlalchemy import DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base


  
class TransacaoEntity(Base):
    __tablename__ = "transacoes"
    
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usuario_telegram_id: Mapped[int] = mapped_column(Integer, index=True)
    
    data: Mapped[str] = mapped_column(String)
    descricao: Mapped[str] = mapped_column(String)
    valor:  Mapped[float] = mapped_column(Float)
    tipo: Mapped[str] = mapped_column(String)
    categoria: Mapped[str] = mapped_column(String, default="")
    
    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)