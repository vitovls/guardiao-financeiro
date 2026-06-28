import os

from telegram import Update

from services.message_service import format_message, split_message
from services.ocr_service import extract_photo_data
from services.transaction_service import save_transactions


async def get_pdf(update: Update, context):
    user_id = update.effective_user.id
    pdf = update.message.document
    pdf_file = await pdf.get_file()
    pdf_path = f"fotos/{pdf.file_unique_id}.pdf"
    await update.message.reply_text("...")
    await pdf_file.download_to_drive(pdf_path)

    try:
        transactions = await extract_photo_data(pdf_path)
    finally:
        os.remove(pdf_path)

    await save_transactions(transactions, user_id)
    msg = format_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
