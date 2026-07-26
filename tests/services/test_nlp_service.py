from datetime import date

from models import Transacao


def _fake_transacao() -> Transacao:
    return Transacao(
        data=date(2026, 7, 26),
        descricao="mercado",
        valor=30.0,
        tipo="saida",
        categoria="alimentacao",
    )


async def test_extract_text_transactions_returns_provider_result(monkeypatch):
    import services.nlp_service as nlp_service

    expected = [_fake_transacao()]

    class _FakeProvider:
        async def extract_text_transactions(self, text: str) -> list[Transacao]:
            return expected

    monkeypatch.setattr(nlp_service, "_provider", _FakeProvider())

    result = await nlp_service.extract_text_transactions("gastei 30 no mercado")

    assert result == expected


async def test_extract_text_transactions_returns_empty_list_when_provider_raises(monkeypatch):
    import services.nlp_service as nlp_service

    class _FailingProvider:
        async def extract_text_transactions(self, text: str) -> list[Transacao]:
            raise RuntimeError("falha inesperada")

    monkeypatch.setattr(nlp_service, "_provider", _FailingProvider())

    result = await nlp_service.extract_text_transactions("gastei 30 no mercado")

    assert result == []
