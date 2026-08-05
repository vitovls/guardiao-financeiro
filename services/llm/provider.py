from abc import ABC, abstractmethod
from datetime import date
from typing import Literal

from pydantic import BaseModel

from models import Transacao


class LLMProviderError(Exception):
    """Erro genérico de provider de LLM, tratado pelos services (nunca vaza ao handler)."""


class BedrockOutputError(LLMProviderError):
    """Bedrock retornou JSON inválido/vazio mesmo após a re-tentativa de output malformado."""


class InterpretacaoTexto(BaseModel):
    intencao: Literal["transacao", "consulta", "nenhuma"]
    transacoes: list[Transacao] = []
    periodo_inicio: date | None = None
    periodo_fim: date | None = None
    categoria: str | None = None


class LLMProvider(ABC):
    @abstractmethod
    async def interpret_text(self, text: str) -> InterpretacaoTexto:
        ...

    @abstractmethod
    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        ...
