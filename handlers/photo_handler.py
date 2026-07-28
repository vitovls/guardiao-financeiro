import sys

from handlers.pending_handler import build_confirmation_keyboard
from services.message_service import format_message, format_pending_message
from services.ocr_service import extract_document_data
from services.storage.factory import get_storage_provider
from services.storage.provider import MAX_FILE_SIZE_BYTES, StorageProviderError
from services.transaction_service import claim_update, save_transactions

_storage = get_storage_provider()


async def get_photo(update, context):
    user_id = update.effective_user.id
    if not await claim_update(user_id, update.update_id):
        return

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

    results = await save_transactions(transactions, user_id)
    message = format_message(results)
    await update.message.reply_text(message, parse_mode="HTML")

    for r in results:
        if r.pendencia:
            await update.message.reply_text(
                format_pending_message(r.pendencia),
                reply_markup=build_confirmation_keyboard(r.pendencia.id),
            )
