from abc import ABC, abstractmethod

from models import Transacao


class LLMProviderError(Exception):
    """Erro genérico de provider de LLM, tratado pelos services (nunca vaza ao handler)."""


class BedrockOutputError(LLMProviderError):
    """Bedrock retornou JSON inválido/vazio mesmo após a re-tentativa de output malformado."""


class LLMProvider(ABC):
    @abstractmethod
    async def extract_text_transactions(self, text: str) -> list[Transacao]:
        ...

    @abstractmethod
    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        ...
