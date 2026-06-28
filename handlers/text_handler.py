from telegram import Update
from telegram.ext import ContextTypes

from services.message_service import formatter_message, split_message
from services.nlp_service import extract_text_transference


async def get_message(update: Update, context: ContextTypes):
    txt = update.message.text
    json = await extract_text_transference(txt)
    msg = formatter_message(json)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")