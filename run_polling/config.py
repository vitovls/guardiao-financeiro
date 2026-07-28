import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "guardiao-financeiro-files-dev-413948096391")
# MEU_USER_ID = int(os.getenv("MEU_TELEGRAM_ID"))