from datetime import date
from typing import Literal

from pydantic import BaseModel, field_validator

DEFAULT_CATEGORIA = "outros"


class Transacao(BaseModel):
    data: date
    descricao: str
    valor: float
    tipo: Literal["entrada", "saida"]
    categoria: str = DEFAULT_CATEGORIA

    @field_validator("categoria")
    @classmethod
    def usa_categoria_padrao_quando_vazia(cls, v: str) -> str:
        return v or DEFAULT_CATEGORIA
