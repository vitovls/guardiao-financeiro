from typing import Literal

from pydantic import BaseModel


class Transacao(BaseModel):
    data: str
    descricao: str
    valor: float
    tipo: Literal["entrada", "saida"]
    categoria: str = ""
