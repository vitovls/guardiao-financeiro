from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.message_service import format_pending_message
from services.transaction_service import get_pending, resolve_pending


def build_confirmation_keyboard(pendencia_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim", callback_data=f"pend:sim:{pendencia_id}"),
        InlineKeyboardButton("🚫 Não", callback_data=f"pend:nao:{pendencia_id}"),
    ]])


async def get_pendencias(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    pendencias = await get_pending(user_id)

    if not pendencias:
        await update.message.reply_text("Nenhuma pendência em aberto. 🎉")
        return

    for pendencia in pendencias:
        texto = format_pending_message(pendencia)
        await update.message.reply_text(texto, reply_markup=build_confirmation_keyboard(pendencia.id))


async def handle_pending_callback(update: Update, context: ContextTypes):
    query = update.callback_query
    await query.answer()

    _, decisao, pendencia_id = query.data.split(":", 2)
    user_id = update.effective_user.id

    resultado = await resolve_pending(user_id, pendencia_id, decisao)

    textos = {
        "confirmada": "✅ Confirmado e salvo.",
        "descartada": "🚫 Descartado — não foi salvo.",
        "ja_resolvida": "Essa pendência já tinha sido resolvida antes.",
    }
    await query.edit_message_text(textos[resultado])
