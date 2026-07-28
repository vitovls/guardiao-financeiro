import pytest

from services.storage.provider import StorageProvider


class _ConcreteProvider(StorageProvider):
    async def upload(self, user_id: int, filename: str, file_bytes: bytes) -> str:
        return "key"

    async def delete(self, key: str) -> None:
        pass


def test_concrete_subclass_can_be_instantiated():
    provider = _ConcreteProvider()
    assert isinstance(provider, StorageProvider)


def test_abstract_class_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        StorageProvider()
