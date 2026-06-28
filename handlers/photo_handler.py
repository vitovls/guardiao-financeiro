from services.ocr_service import extract_photo_data, formatter_message


async def get_photo(update, context):
    # if not usuario_autorizado(update.effective_user.id):
    #     await update.message.reply_text("Acesso não autorizado.")
    #     return

    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"fotos/{photo.file_unique_id}.jpg"
    await update.message.reply_text("...")
    await file.download_to_drive(path)

    json_extraido = await extract_photo_data(path)
    mensagem = formatter_message(json_extraido)
    await update.message.reply_text(mensagem, parse_mode="HTML")
