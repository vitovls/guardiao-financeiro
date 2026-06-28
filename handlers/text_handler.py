from telegram import Update
from telegram.ext import ContextTypes

from services.message_service import format_message, split_message
from services.nlp_service import extract_text_transactions
from services.transaction_service import save_transactions


async def get_message(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    text = update.message.text
    transactions = await extract_text_transactions(text)

    if not transactions:
        await update.message.reply_text(
            "Não foi identificada nenhuma transação nessa mensagem."
            " Tente algo como 'Gastei 30 reais no mercado'"
        )
        return

    await save_transactions(transactions, user_id)

    msg = format_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
