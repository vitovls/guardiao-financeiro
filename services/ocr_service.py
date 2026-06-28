import json

from google import genai
from google.genai import types

from models import Transacao
from prompts import TRANSACTION_SCHEMA
from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_photo_data(image_path: str) -> list[Transacao]:
    with open(image_path, "rb") as f:
        file_bytes = f.read()

    if image_path.endswith(".jpg"):
        mime_type = "image/jpeg"
        prompt = "Extraia as transações desta imagem de extrato bancário. "
    elif image_path.endswith(".pdf"):
        mime_type = "application/pdf"
        prompt = "Extraia as transações desse pdf de extrato bancário. "
    else:
        raise ValueError(f"Formato não suportado: {image_path}")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            (prompt + f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"),
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    response_data = json.loads(response.text)
    return [Transacao(**item) for item in response_data]
