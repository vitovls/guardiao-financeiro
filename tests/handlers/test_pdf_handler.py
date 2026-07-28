from unittest.mock import AsyncMock, Mock

from services.storage.provider import StorageProviderError


def _build_update(file_size: int = 1000, file_bytes: bytes = b"fake-bytes", mime_type: str = "application/pdf"):
    pdf = Mock()
    pdf.file_size = file_size
    pdf.file_unique_id = "abc123"
    pdf.file_name = "extrato.pdf"
    pdf.mime_type = mime_type

    telegram_file = AsyncMock()
    telegram_file.download_as_bytearray.return_value = bytearray(file_bytes)
    pdf.get_file = AsyncMock(return_value=telegram_file)

    update = Mock()
    update.effective_user.id = 42
    update.message.document = pdf
    update.message.reply_text = AsyncMock()

    return update, pdf


async def test_happy_path_uploads_extracts_deletes_and_replies(monkeypatch):
    import handlers.pdf_handler as pdf_handler

    update, pdf = _build_update()
    context = Mock()

    storage = AsyncMock()
    storage.upload.return_value = "files/42-123-extrato.pdf"
    monkeypatch.setattr(pdf_handler, "_storage", storage)

    extract_document_data = AsyncMock(return_value=["transacao-fake"])
    monkeypatch.setattr(pdf_handler, "extract_document_data", extract_document_data)
    monkeypatch.setattr(pdf_handler, "save_transactions", AsyncMock())
    monkeypatch.setattr(pdf_handler, "format_message", Mock(return_value="mensagem formatada"))

    await pdf_handler.get_pdf(update, context)

    storage.upload.assert_awaited_once()
    upload_args = storage.upload.call_args.args
    assert upload_args[0] == 42
    assert upload_args[2] == b"fake-bytes"

    extract_document_data.assert_awaited_once_with(b"fake-bytes", "application/pdf")
    storage.delete.assert_awaited_once_with("files/42-123-extrato.pdf")

    update.message.reply_text.assert_any_call("mensagem formatada", parse_mode="HTML")


async def test_file_too_large_replies_and_does_not_call_get_file(monkeypatch):
    import handlers.pdf_handler as pdf_handler
    from services.storage.provider import MAX_FILE_SIZE_BYTES

    update, pdf = _build_update(file_size=MAX_FILE_SIZE_BYTES + 1)
    context = Mock()

    storage = AsyncMock()
    monkeypatch.setattr(pdf_handler, "_storage", storage)

    await pdf_handler.get_pdf(update, context)

    pdf.get_file.assert_not_called()
    storage.upload.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()


async def test_upload_failure_replies_error_and_does_not_extract(monkeypatch):
    import handlers.pdf_handler as pdf_handler

    update, pdf = _build_update()
    context = Mock()

    storage = AsyncMock()
    storage.upload.side_effect = StorageProviderError("falha")
    monkeypatch.setattr(pdf_handler, "_storage", storage)

    extract_document_data = AsyncMock()
    monkeypatch.setattr(pdf_handler, "extract_document_data", extract_document_data)

    await pdf_handler.get_pdf(update, context)

    extract_document_data.assert_not_awaited()
    update.message.reply_text.assert_awaited()


async def test_missing_mime_type_falls_back_to_application_pdf(monkeypatch):
    import handlers.pdf_handler as pdf_handler

    update, pdf = _build_update(mime_type=None)
    context = Mock()

    storage = AsyncMock()
    storage.upload.return_value = "files/42-123-extrato.pdf"
    monkeypatch.setattr(pdf_handler, "_storage", storage)

    extract_document_data = AsyncMock(return_value=[])
    monkeypatch.setattr(pdf_handler, "extract_document_data", extract_document_data)
    monkeypatch.setattr(pdf_handler, "save_transactions", AsyncMock())
    monkeypatch.setattr(pdf_handler, "format_message", Mock(return_value="mensagem formatada"))

    await pdf_handler.get_pdf(update, context)

    extract_document_data.assert_awaited_once_with(b"fake-bytes", "application/pdf")
