from datetime import date
from typing import Literal

from pydantic import BaseModel


class Transacao(BaseModel):
    data: date
    descricao: str
    valor: float
    tipo: Literal["entrada", "saida"]
    categoria: str = ""
