import sys

from models import Transacao
from services.llm.factory import get_llm_provider

_provider = get_llm_provider()


async def extract_photo_data(image_path: str) -> list[Transacao]:
    with open(image_path, "rb") as f:
        file_bytes = f.read()

    if image_path.endswith(".jpg"):
        mime_type = "image/jpeg"
    elif image_path.endswith(".pdf"):
        mime_type = "application/pdf"
    else:
        raise ValueError(f"Formato não suportado: {image_path}")

    try:
        return await _provider.extract_document_transactions(file_bytes, mime_type)
    except Exception as exc:
        print(f"[ocr_service] falha ao extrair transação de documento: {exc}", file=sys.stderr)
        return []
