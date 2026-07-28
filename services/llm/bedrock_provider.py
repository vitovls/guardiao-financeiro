import asyncio
import json
import random
from datetime import date

import boto3
from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError
from pydantic import ValidationError

from models import Transacao
from prompts import build_document_extraction_prompt, build_text_extraction_prompt
from services.llm.provider import BedrockOutputError, LLMProvider

REGION = "us-east-2"
TEXT_MODEL_ID = "us.meta.llama4-maverick-17b-instruct-v1:0"
DOCUMENT_MODEL_ID = "us.meta.llama4-maverick-17b-instruct-v1:0"

_MIME_TO_IMAGE_FORMAT = {"image/jpeg": "jpeg"}
_MIME_TO_DOCUMENT_FORMAT = {"application/pdf": "pdf"}
_DOCUMENT_NAME = "extrato bancario"

_MAX_ATTEMPTS = 3
_BASE_INTERVAL_SECONDS = 1
_BACKOFF_RATE = 2
_RETRYABLE_ERROR_CODES = {"ThrottlingException"}

# Sem isso, o Converse API usa o default de 2000 tokens de saída, insuficiente
# para extratos reais com muitas transações — a resposta trunca no meio do
# JSON e falha a validação.
_MAX_OUTPUT_TOKENS = 5000


async def _converse_with_retry(
    client, model_id: str, messages: list[dict], temperature: float | None = None
) -> str:
    inference_config = {"maxTokens": _MAX_OUTPUT_TOKENS}
    if temperature is not None:
        inference_config["temperature"] = temperature

    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig=inference_config,
            )
            return response["output"]["message"]["content"][0]["text"]
        except ClientError as exc:
            error_code = exc.response["Error"]["Code"]
            is_last_attempt = attempt == _MAX_ATTEMPTS - 1
            if error_code not in _RETRYABLE_ERROR_CODES or is_last_attempt:
                raise
        except (ConnectTimeoutError, ReadTimeoutError):
            if attempt == _MAX_ATTEMPTS - 1:
                raise

        cap = _BASE_INTERVAL_SECONDS * (_BACKOFF_RATE**attempt)
        await asyncio.sleep(random.uniform(0, cap))


def _strip_markdown_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()


class BedrockProvider(LLMProvider):
    def __init__(self, client=None):
        self._client = client or boto3.client("bedrock-runtime", region_name=REGION)

    async def extract_text_transactions(self, text: str) -> list[Transacao]:
        prompt = build_text_extraction_prompt(date.today().isoformat(), text)
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        return await self._call_with_malformed_retry(TEXT_MODEL_ID, messages, self._parse_text_response)

    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        label = "PDF" if mime_type in _MIME_TO_DOCUMENT_FORMAT else "imagem"
        prompt = build_document_extraction_prompt(label)
        content_block = self._build_content_block(file_bytes, mime_type)
        messages = [{"role": "user", "content": [content_block, {"text": prompt}]}]
        return await self._call_with_malformed_retry(
            DOCUMENT_MODEL_ID, messages, self._parse_document_response, temperature=0.0
        )

    def _parse_text_response(self, response_data: dict) -> list[Transacao]:
        if not response_data.get("e_transacao"):
            return []
        return [Transacao(**item) for item in response_data["transacoes"]]

    def _parse_document_response(self, response_data: list) -> list[Transacao]:
        return [Transacao(**item) for item in response_data]

    def _build_content_block(self, file_bytes: bytes, mime_type: str) -> dict:
        if mime_type in _MIME_TO_IMAGE_FORMAT:
            return {"image": {"format": _MIME_TO_IMAGE_FORMAT[mime_type], "source": {"bytes": file_bytes}}}
        if mime_type in _MIME_TO_DOCUMENT_FORMAT:
            return {
                "document": {
                    "format": _MIME_TO_DOCUMENT_FORMAT[mime_type],
                    "name": _DOCUMENT_NAME,
                    "source": {"bytes": file_bytes},
                }
            }
        raise ValueError(f"mime_type não suportado: {mime_type}")

    async def _call_with_malformed_retry(
        self, model_id: str, messages: list[dict], parse_fn, temperature: float | None = None
    ) -> list[Transacao]:
        for attempt in range(2):
            text = await _converse_with_retry(self._client, model_id, messages, temperature=temperature)
            try:
                response_data = json.loads(_strip_markdown_fence(text))
                return parse_fn(response_data)
            except (json.JSONDecodeError, KeyError, ValidationError):
                if attempt == 1:
                    raise BedrockOutputError("Bedrock retornou JSON inválido após re-tentativa")
