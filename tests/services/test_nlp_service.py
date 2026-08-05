from datetime import date

from models import Transacao
from services.llm.provider import InterpretacaoTexto


def _fake_transacao() -> Transacao:
    return Transacao(
        data=date(2026, 7, 26),
        descricao="mercado",
        valor=30.0,
        tipo="saida",
        categoria="alimentacao",
    )


async def test_interpret_text_returns_provider_result(monkeypatch):
    import services.nlp_service as nlp_service

    expected = InterpretacaoTexto(intencao="transacao", transacoes=[_fake_transacao()])

    class _FakeProvider:
        async def interpret_text(self, text: str) -> InterpretacaoTexto:
            return expected

    monkeypatch.setattr(nlp_service, "_provider", _FakeProvider())

    result = await nlp_service.interpret_text("gastei 30 no mercado")

    assert result == expected


async def test_interpret_text_returns_nenhuma_when_provider_raises(monkeypatch):
    import services.nlp_service as nlp_service

    class _FailingProvider:
        async def interpret_text(self, text: str) -> InterpretacaoTexto:
            raise RuntimeError("falha inesperada")

    monkeypatch.setattr(nlp_service, "_provider", _FailingProvider())

    result = await nlp_service.interpret_text("gastei 30 no mercado")

    assert result == InterpretacaoTexto(intencao="nenhuma")
