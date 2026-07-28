from datetime import date

from models import Transacao


def _fake_transacao() -> Transacao:
    return Transacao(
        data=date(2026, 7, 26),
        descricao="padaria",
        valor=15.0,
        tipo="saida",
        categoria="alimentacao",
    )


async def test_extract_document_data_returns_provider_result(monkeypatch):
    import services.ocr_service as ocr_service

    expected = [_fake_transacao()]

    class _FakeProvider:
        async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
            return expected

    monkeypatch.setattr(ocr_service, "_provider", _FakeProvider())

    result = await ocr_service.extract_document_data(b"fake-bytes", "image/jpeg")

    assert result == expected


async def test_extract_document_data_returns_empty_list_when_provider_raises(monkeypatch):
    import services.ocr_service as ocr_service

    class _FailingProvider:
        async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
            raise RuntimeError("falha inesperada")

    monkeypatch.setattr(ocr_service, "_provider", _FailingProvider())

    result = await ocr_service.extract_document_data(b"fake-bytes", "image/jpeg")

    assert result == []
