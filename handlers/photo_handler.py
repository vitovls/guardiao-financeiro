from services.message_service import formatter_message
from services.ocr_service import extract_photo_data
from services.transacao_service import salvar_transacoes


async def get_photo(update, context):
    usuario_id = update.effective_user.id
    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"fotos/{photo.file_unique_id}.jpg"
    await update.message.reply_text("...")
    await file.download_to_drive(path)

    transactions = await extract_photo_data(path)
    await salvar_transacoes(transactions, usuario_id)
    mensagem = formatter_message(transactions)
    await update.message.reply_text(mensagem, parse_mode="HTML")
