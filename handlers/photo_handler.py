from services.message_service import formatter_message
from services.ocr_service import extract_photo_data


async def get_photo(update, context):
    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"fotos/{photo.file_unique_id}.jpg"
    await update.message.reply_text("...")
    await file.download_to_drive(path)

    json_extraido = await extract_photo_data(path)
    mensagem = formatter_message(json_extraido)
    await update.message.reply_text(mensagem, parse_mode="HTML")
