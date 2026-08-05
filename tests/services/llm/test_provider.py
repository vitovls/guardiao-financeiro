import pytest
from pydantic import ValidationError

from services.llm.provider import InterpretacaoTexto, LLMProvider
from models import Transacao


class _ConcreteProvider(LLMProvider):
    async def interpret_text(self, text: str) -> InterpretacaoTexto:
        return InterpretacaoTexto(intencao="nenhuma")

    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        return []


def test_concrete_subclass_can_be_instantiated():
    provider = _ConcreteProvider()
    assert isinstance(provider, LLMProvider)


def test_abstract_class_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        LLMProvider()


def test_interpretacao_texto_transacao_accepts_defaults():
    interpretacao = InterpretacaoTexto(intencao="transacao")
    assert interpretacao.transacoes == []
    assert interpretacao.periodo_inicio is None
    assert interpretacao.periodo_fim is None
    assert interpretacao.categoria is None


def test_interpretacao_texto_invalid_intencao_raises_validation_error():
    with pytest.raises(ValidationError):
        InterpretacaoTexto(intencao="invalido")
