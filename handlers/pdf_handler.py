import sys

from telegram import Update

from services.message_service import format_message, split_message
from services.ocr_service import extract_document_data
from services.storage.factory import get_storage_provider
from services.storage.provider import MAX_FILE_SIZE_BYTES, StorageProviderError
from services.transaction_service import save_transactions

_storage = get_storage_provider()


async def get_pdf(update: Update, context):
    user_id = update.effective_user.id
    pdf = update.message.document

    if pdf.file_size and pdf.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text("Arquivo muito grande (máx. 20MB). Envie um PDF menor.")
        return

    pdf_file = await pdf.get_file()
    await update.message.reply_text("🔍 Recebi! Já vou dar uma olhada nisso...")
    file_bytes = bytes(await pdf_file.download_as_bytearray())
    mime_type = pdf.mime_type or "application/pdf"

    try:
        key = await _storage.upload(user_id, pdf.file_name or f"{pdf.file_unique_id}.pdf", file_bytes)
    except StorageProviderError:
        await update.message.reply_text("Não consegui processar seu PDF agora, tenta de novo.")
        return

    try:
        transactions = await extract_document_data(file_bytes, mime_type)
    finally:
        try:
            await _storage.delete(key)
        except Exception as exc:
            print(f"[pdf_handler] falha ao deletar {key} do storage: {exc}", file=sys.stderr)

    await save_transactions(transactions, user_id)
    msg = format_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
