from unittest.mock import AsyncMock, Mock

from services.storage.provider import StorageProviderError


def _build_update(file_size: int = 1000, file_bytes: bytes = b"fake-bytes"):
    photo = Mock()
    photo.file_size = file_size
    photo.file_unique_id = "abc123"

    telegram_file = AsyncMock()
    telegram_file.download_as_bytearray.return_value = bytearray(file_bytes)
    photo.get_file = AsyncMock(return_value=telegram_file)

    update = Mock()
    update.effective_user.id = 42
    update.message.photo = [photo]
    update.message.reply_text = AsyncMock()

    return update, photo


async def test_happy_path_uploads_extracts_deletes_and_replies(monkeypatch):
    import handlers.photo_handler as photo_handler

    update, photo = _build_update()
    context = Mock()

    storage = AsyncMock()
    storage.upload.return_value = "files/42-123-abc123.jpg"
    monkeypatch.setattr(photo_handler, "_storage", storage)

    extract_document_data = AsyncMock(return_value=["transacao-fake"])
    monkeypatch.setattr(photo_handler, "extract_document_data", extract_document_data)
    save_transactions = AsyncMock(return_value=["resultado-fake"])
    monkeypatch.setattr(photo_handler, "save_transactions", save_transactions)
    format_message = Mock(return_value="mensagem formatada")
    monkeypatch.setattr(photo_handler, "format_message", format_message)

    await photo_handler.get_photo(update, context)

    storage.upload.assert_awaited_once()
    upload_args = storage.upload.call_args.args
    assert upload_args[0] == 42
    assert upload_args[2] == b"fake-bytes"

    extract_document_data.assert_awaited_once_with(b"fake-bytes", "image/jpeg")
    storage.delete.assert_awaited_once_with("files/42-123-abc123.jpg")

    save_transactions.assert_awaited_once_with(["transacao-fake"], 42)
    format_message.assert_called_once_with(["resultado-fake"])
    update.message.reply_text.assert_any_call("mensagem formatada", parse_mode="HTML")


async def test_file_too_large_replies_and_does_not_call_get_file(monkeypatch):
    import handlers.photo_handler as photo_handler
    from services.storage.provider import MAX_FILE_SIZE_BYTES

    update, photo = _build_update(file_size=MAX_FILE_SIZE_BYTES + 1)
    context = Mock()

    storage = AsyncMock()
    monkeypatch.setattr(photo_handler, "_storage", storage)

    await photo_handler.get_photo(update, context)

    photo.get_file.assert_not_called()
    storage.upload.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()


async def test_upload_failure_replies_error_and_does_not_extract(monkeypatch):
    import handlers.photo_handler as photo_handler

    update, photo = _build_update()
    context = Mock()

    storage = AsyncMock()
    storage.upload.side_effect = StorageProviderError("falha")
    monkeypatch.setattr(photo_handler, "_storage", storage)

    extract_document_data = AsyncMock()
    monkeypatch.setattr(photo_handler, "extract_document_data", extract_document_data)

    await photo_handler.get_photo(update, context)

    extract_document_data.assert_not_awaited()
    update.message.reply_text.assert_awaited()
