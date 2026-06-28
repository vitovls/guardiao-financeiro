from telegram import Update
from telegram.ext import ContextTypes

from services.message_service import formatter_message, split_message
from services.nlp_service import extract_text_transference


async def get_message(update: Update, context: ContextTypes):
    txt = update.message.text
    transactions = await extract_text_transference(txt)

    if not transactions:
        await update.message.reply_text(
            "Não foi identificada nenhuma transação nessa mensagem."
            " Tente algo como 'Gastei 30 reais no mercado'"
        )
        return

    msg = formatter_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
