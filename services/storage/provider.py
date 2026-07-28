from abc import ABC, abstractmethod

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024


class StorageProviderError(Exception):
    """Erro genérico de provider de storage, tratado pelos handlers (nunca vaza cru ao usuário)."""


class StorageProvider(ABC):
    @abstractmethod
    async def upload(self, user_id: int, filename: str, file_bytes: bytes) -> str:
        """Persiste os bytes e retorna a chave de armazenamento."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove o objeto identificado por `key`."""
