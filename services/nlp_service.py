import sys

from models import Transacao
from services.llm.factory import get_llm_provider

_provider = get_llm_provider()


async def extract_text_transactions(text: str) -> list[Transacao]:
    try:
        return await _provider.extract_text_transactions(text)
    except Exception as exc:
        print(f"[nlp_service] falha ao extrair transação de texto: {exc}", file=sys.stderr)
        return []
