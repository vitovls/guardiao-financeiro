import os

from telegram import Update

from services.message_service import formatter_message, split_message
from services.ocr_service import extract_photo_data
from services.transacao_service import salvar_transacoes


async def get_pdf(update: Update, context):
    usuario_id = update.effective_user.id
    pdf = update.message.document
    file_pdf = await pdf.get_file()
    path_pdf = f"fotos/{pdf.file_unique_id}.pdf"
    await update.message.reply_text("...")
    await file_pdf.download_to_drive(path_pdf)

    try:
        transactions = await extract_photo_data(path_pdf)
    finally:
        os.remove(path_pdf)

    await salvar_transacoes(transactions, usuario_id)
    msg = formatter_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
