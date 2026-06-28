from telegram import Update

from services.message_service import split_message
from services.ocr_service import extract_photo_data, formatter_message


async def get_pdf(update: Update, context):
    pdf = update.message.document
    file_pdf = await pdf.get_file()
    path_pdf = f"fotos/{pdf.file_unique_id}.pdf"
    await update.message.reply_text("...")
    await file_pdf.download_to_drive(path_pdf)

    json_extraido = await extract_photo_data(path_pdf)
    msg = formatter_message(json_extraido)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
