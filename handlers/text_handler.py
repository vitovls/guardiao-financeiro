from telegram import Update
from telegram.ext import ContextTypes

from handlers.pending_handler import build_confirmation_keyboard
from services.llm.provider import InterpretacaoTexto
from services.message_service import (
    format_message,
    format_missing_period_message,
    format_no_intent_message,
    format_pending_message,
    format_query_message,
    split_message,
)
from services.nlp_service import interpret_text
from services.transaction_service import claim_update, get_totals, save_transactions


async def get_message(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if not await claim_update(user_id, update.update_id):
        return

    text = update.message.text
    interpretacao = await interpret_text(text)

    if interpretacao.intencao == "consulta":
        await _handle_query(update, user_id, interpretacao)
        return

    if interpretacao.intencao != "transacao" or not interpretacao.transacoes:
        await update.message.reply_text(format_no_intent_message())
        return

    results = await save_transactions(interpretacao.transacoes, user_id)

    msg = format_message(results)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")

    for r in results:
        if r.pendencia:
            await update.message.reply_text(
                format_pending_message(r.pendencia),
                reply_markup=build_confirmation_keyboard(r.pendencia.id),
            )


async def _handle_query(update: Update, user_id: int, interpretacao: InterpretacaoTexto) -> None:
    if interpretacao.periodo_inicio is None or interpretacao.periodo_fim is None:
        await update.message.reply_text(format_missing_period_message())
        return

    totals = await get_totals(
        user_id, interpretacao.periodo_inicio, interpretacao.periodo_fim, interpretacao.categoria
    )
    msg = format_query_message(
        interpretacao.periodo_inicio, interpretacao.periodo_fim, interpretacao.categoria, totals
    )
    await update.message.reply_text(msg)
