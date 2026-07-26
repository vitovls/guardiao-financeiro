import pytest

from services.llm.provider import LLMProvider
from models import Transacao


class _ConcreteProvider(LLMProvider):
    async def extract_text_transactions(self, text: str) -> list[Transacao]:
        return []

    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        return []


def test_concrete_subclass_can_be_instantiated():
    provider = _ConcreteProvider()
    assert isinstance(provider, LLMProvider)


def test_abstract_class_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        LLMProvider()
