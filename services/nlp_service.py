import sys

from services.llm.factory import get_llm_provider
from services.llm.provider import InterpretacaoTexto

_provider = get_llm_provider()


async def interpret_text(text: str) -> InterpretacaoTexto:
    try:
        return await _provider.interpret_text(text)
    except Exception as exc:
        print(f"[nlp_service] falha ao interpretar mensagem de texto: {exc}", file=sys.stderr)
        return InterpretacaoTexto(intencao="nenhuma")
