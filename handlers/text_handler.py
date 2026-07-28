from telegram import Update
from telegram.ext import ContextTypes

from handlers.pending_handler import build_confirmation_keyboard
from services.message_service import format_message, format_pending_message, split_message
from services.nlp_service import extract_text_transactions
from services.transaction_service import claim_update, save_transactions


async def get_message(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if not await claim_update(user_id, update.update_id):
        return

    text = update.message.text
    transactions = await extract_text_transactions(text)

    if not transactions:
        await update.message.reply_text(
            "Não foi identificada nenhuma transação nessa mensagem."
            " Tente algo como 'Gastei 30 reais no mercado'"
        )
        return

    results = await save_transactions(transactions, user_id)

    msg = format_message(results)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")

    for r in results:
        if r.pendencia:
            await update.message.reply_text(
                format_pending_message(r.pendencia),
                reply_markup=build_confirmation_keyboard(r.pendencia.id),
            )
