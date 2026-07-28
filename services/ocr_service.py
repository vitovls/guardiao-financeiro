import sys

from models import Transacao
from services.llm.factory import get_llm_provider

_provider = get_llm_provider()


async def extract_document_data(file_bytes: bytes, mime_type: str) -> list[Transacao]:
    try:
        return await _provider.extract_document_transactions(file_bytes, mime_type)
    except Exception as exc:
        print(f"[ocr_service] falha ao extrair transação de documento: {exc}", file=sys.stderr)
        return []
