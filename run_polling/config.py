import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
# MEU_USER_ID = int(os.getenv("MEU_TELEGRAM_ID"))