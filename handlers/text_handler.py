from telegram import Update
from telegram.ext import ContextTypes

from services.message_service import formatter_message, split_message
from services.nlp_service import extract_text_transference
from services.transacao_service import salvar_transacoes


async def get_message(update: Update, context: ContextTypes):
    usuario_id = update.effective_user.id
    txt = update.message.text
    transactions = await extract_text_transference(txt)

    if not transactions:
        await update.message.reply_text(
            "Não foi identificada nenhuma transação nessa mensagem."
            " Tente algo como 'Gastei 30 reais no mercado'"
        )
        return

    await salvar_transacoes(transactions, usuario_id)

    msg = formatter_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
