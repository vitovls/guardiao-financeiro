from run_polling.config import BOT_TOKEN
from telegram.ext import Application, MessageHandler, filters

from handlers.text_handler import get_message


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, get_message))
    print("Bot rodando... aguardando mensagens.")
    app.run_polling()

if __name__ == "__main__":
    main()