import os

from services.message_service import format_message
from services.ocr_service import extract_photo_data
from services.transaction_service import save_transactions


async def get_photo(update, context):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"fotos/{photo.file_unique_id}.jpg"
    await update.message.reply_text("...")
    await file.download_to_drive(path)

    try:
        transactions = await extract_photo_data(path)
    finally:
        os.remove(path)

    await save_transactions(transactions, user_id)
    message = format_message(transactions)
    await update.message.reply_text(message, parse_mode="HTML")
