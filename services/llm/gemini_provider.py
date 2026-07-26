import json
from datetime import date

from google import genai
from google.genai import types

from models import Transacao
from prompts import build_document_extraction_prompt, build_text_extraction_prompt
from run_polling.config import GEMINI_API_KEY
from services.llm.provider import LLMProvider

_MIME_TO_LABEL = {"image/jpeg": "imagem", "application/pdf": "PDF"}
_MODEL = "gemini-2.5-flash"


class GeminiProvider(LLMProvider):
    def __init__(self, client=None):
        self._client = client or genai.Client(api_key=GEMINI_API_KEY)

    async def extract_text_transactions(self, text: str) -> list[Transacao]:
        prompt = build_text_extraction_prompt(date.today().isoformat(), text)
        response = self._client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        response_data = json.loads(response.text)
        if not response_data.get("e_transacao"):
            return []
        return [Transacao(**item) for item in response_data["transacoes"]]

    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        label = _MIME_TO_LABEL.get(mime_type, "documento")
        prompt = build_document_extraction_prompt(label)
        response = self._client.models.generate_content(
            model=_MODEL,
            contents=[types.Part.from_bytes(data=file_bytes, mime_type=mime_type), prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        response_data = json.loads(response.text)
        return [Transacao(**item) for item in response_data]
