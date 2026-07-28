import sys

from services.message_service import format_message
from services.ocr_service import extract_document_data
from services.storage.factory import get_storage_provider
from services.storage.provider import MAX_FILE_SIZE_BYTES, StorageProviderError
from services.transaction_service import save_transactions

_storage = get_storage_provider()


async def get_photo(update, context):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]

    if photo.file_size and photo.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text("Arquivo muito grande (máx. 20MB). Envie uma foto menor.")
        return

    file = await photo.get_file()
    await update.message.reply_text("🔍 Recebi! Já vou dar uma olhada nisso...")
    file_bytes = bytes(await file.download_as_bytearray())

    try:
        key = await _storage.upload(user_id, f"{photo.file_unique_id}.jpg", file_bytes)
    except StorageProviderError:
        await update.message.reply_text("Não consegui processar sua foto agora, tenta de novo.")
        return

    try:
        transactions = await extract_document_data(file_bytes, "image/jpeg")
    finally:
        try:
            await _storage.delete(key)
        except Exception as exc:
            print(f"[photo_handler] falha ao deletar {key} do storage: {exc}", file=sys.stderr)

    await save_transactions(transactions, user_id)
    message = format_message(transactions)
    await update.message.reply_text(message, parse_mode="HTML")
