from run_polling.config import LLM_PROVIDER
from services.llm.bedrock_provider import BedrockProvider
from services.llm.gemini_provider import GeminiProvider
from services.llm.provider import LLMProvider


def get_llm_provider() -> LLMProvider:
    if LLM_PROVIDER == "gemini":
        return GeminiProvider()
    if LLM_PROVIDER == "bedrock":
        return BedrockProvider()
    raise ValueError(f"LLM_PROVIDER inválido: {LLM_PROVIDER!r} (esperado 'gemini' ou 'bedrock')")
