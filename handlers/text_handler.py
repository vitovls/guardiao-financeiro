import json

from telegram import Update
from telegram.ext import ContextTypes

from services.message_service import formatter_message, split_message
from services.nlp_service import extract_text_transference


async def get_message(update: Update, context: ContextTypes):
    txt = update.message.text
    json_data = await extract_text_transference(txt)
    
    try:
        json_dict = json.loads(json_data)
    except json.JSONDecodeError:
        await update.message.reply_text("Não consegui entender sua mensagem")
        return
    
    if not json_dict.get("e_transacao"):
        await update.message.reply_text(
          "Não foi identificado nenhuma transação nessa mensagem."
          " Tente algo como 'Gastei 30 reais no mercado'"
        )
        return
    
    transactions = json.dump(json_data["transacoes"])
        
    msg = formatter_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")