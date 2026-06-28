from telegram.ext import Application, MessageHandler, filters

from handlers.pdf_handler import get_pdf
from handlers.photo_handler import get_photo
from handlers.text_handler import get_message
from run_polling.config import BOT_TOKEN


def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, get_message))
    app.add_handler(MessageHandler(filters.PHOTO, get_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, get_pdf))
    print("Bot rodando... aguardando mensagens.")
    app.run_polling()

if __name__ == "__main__":
    main()