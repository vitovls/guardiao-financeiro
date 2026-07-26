import json
from unittest.mock import Mock, patch

import pytest
from botocore.exceptions import ClientError

from services.llm.bedrock_provider import (
    DOCUMENT_MODEL_ID,
    TEXT_MODEL_ID,
    BedrockProvider,
)
from services.llm.provider import BedrockOutputError


def _response(text: str) -> dict:
    return {"output": {"message": {"content": [{"text": text}]}}}


def _throttling_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "rate exceeded"}},
        "Converse",
    )


def _validation_error() -> ClientError:
    return ClientError(
        {"Error": {"Code": "ValidationException", "Message": "bad request"}},
        "Converse",
    )


def _mock_client(response_text: str) -> Mock:
    client = Mock()
    client.converse.return_value = {
        "output": {"message": {"content": [{"text": response_text}]}}
    }
    return client


async def test_extract_text_transactions_returns_transacoes_and_calls_converse_correctly():
    response_text = json.dumps(
        {
            "e_transacao": True,
            "transacoes": [
                {
                    "data": "2026-07-26",
                    "descricao": "mercado",
                    "valor": 30.0,
                    "tipo": "saida",
                    "categoria": "alimentacao",
                }
            ],
        }
    )
    client = _mock_client(response_text)
    provider = BedrockProvider(client=client)

    result = await provider.extract_text_transactions("gastei 30 no mercado")

    assert len(result) == 1
    assert result[0].descricao == "mercado"
    call_kwargs = client.converse.call_args.kwargs
    assert call_kwargs["modelId"] == TEXT_MODEL_ID
    assert "gastei 30 no mercado" in call_kwargs["messages"][0]["content"][0]["text"]


async def test_extract_document_transactions_image_jpeg_sends_image_content_block():
    response_text = json.dumps([])
    client = _mock_client(response_text)
    provider = BedrockProvider(client=client)

    await provider.extract_document_transactions(b"fake-bytes", "image/jpeg")

    call_kwargs = client.converse.call_args.kwargs
    assert call_kwargs["modelId"] == DOCUMENT_MODEL_ID
    content_block = call_kwargs["messages"][0]["content"][0]
    assert content_block == {"image": {"format": "jpeg", "source": {"bytes": b"fake-bytes"}}}


async def test_extract_document_transactions_pdf_sends_document_content_block():
    response_text = json.dumps([])
    client = _mock_client(response_text)
    provider = BedrockProvider(client=client)

    await provider.extract_document_transactions(b"fake-bytes", "application/pdf")

    call_kwargs = client.converse.call_args.kwargs
    content_block = call_kwargs["messages"][0]["content"][0]
    assert content_block == {
        "document": {
            "format": "pdf",
            "name": "extrato bancario",
            "source": {"bytes": b"fake-bytes"},
        }
    }


async def test_extract_text_transactions_sets_max_tokens_to_avoid_truncation():
    response_text = json.dumps({"e_transacao": False, "transacoes": []})
    client = _mock_client(response_text)
    provider = BedrockProvider(client=client)

    await provider.extract_text_transactions("oi")

    call_kwargs = client.converse.call_args.kwargs
    assert call_kwargs["inferenceConfig"]["maxTokens"] > 2000


async def test_extract_document_transactions_unsupported_mime_raises_value_error():
    client = _mock_client(json.dumps([]))
    provider = BedrockProvider(client=client)

    with pytest.raises(ValueError):
        await provider.extract_document_transactions(b"fake-bytes", "image/png")


@patch("services.llm.bedrock_provider.asyncio.sleep")
async def test_throttling_retries_and_succeeds_on_third_attempt(mock_sleep):
    ok_response = {
        "output": {"message": {"content": [{"text": json.dumps({"e_transacao": False, "transacoes": []})}]}}
    }
    client = Mock()
    client.converse.side_effect = [_throttling_error(), _throttling_error(), ok_response]
    provider = BedrockProvider(client=client)

    result = await provider.extract_text_transactions("oi")

    assert result == []
    assert client.converse.call_count == 3


@patch("services.llm.bedrock_provider.asyncio.sleep")
async def test_throttling_on_all_attempts_propagates(mock_sleep):
    client = Mock()
    client.converse.side_effect = [_throttling_error(), _throttling_error(), _throttling_error()]
    provider = BedrockProvider(client=client)

    with pytest.raises(ClientError):
        await provider.extract_text_transactions("oi")

    assert client.converse.call_count == 3


@patch("services.llm.bedrock_provider.asyncio.sleep")
async def test_validation_error_propagates_immediately_without_retry(mock_sleep):
    client = Mock()
    client.converse.side_effect = [_validation_error()]
    provider = BedrockProvider(client=client)

    with pytest.raises(ClientError):
        await provider.extract_text_transactions("oi")

    assert client.converse.call_count == 1


async def test_malformed_output_retries_once_and_succeeds_on_second_attempt():
    ok_text = json.dumps({"e_transacao": False, "transacoes": []})
    client = Mock()
    client.converse.side_effect = [_response("isso não é JSON"), _response(ok_text)]
    provider = BedrockProvider(client=client)

    result = await provider.extract_text_transactions("oi")

    assert result == []
    assert client.converse.call_count == 2


async def test_malformed_output_on_both_attempts_raises_bedrock_output_error():
    client = Mock()
    client.converse.side_effect = [_response("não json"), _response("ainda não json")]
    provider = BedrockProvider(client=client)

    with pytest.raises(BedrockOutputError):
        await provider.extract_text_transactions("oi")

    assert client.converse.call_count == 2


async def test_missing_expected_key_retries_and_raises_bedrock_output_error_if_persists():
    missing_key_text = json.dumps({"e_transacao": True})
    client = Mock()
    client.converse.side_effect = [_response(missing_key_text), _response(missing_key_text)]
    provider = BedrockProvider(client=client)

    with pytest.raises(BedrockOutputError):
        await provider.extract_text_transactions("oi")

    assert client.converse.call_count == 2


async def test_pydantic_validation_failure_retries_and_raises_bedrock_output_error_if_persists():
    invalid_item_text = json.dumps(
        {
            "e_transacao": True,
            "transacoes": [
                {
                    "data": "2026-07-26",
                    "descricao": "mercado",
                    "valor": 30.0,
                    "tipo": "invalido",
                    "categoria": "alimentacao",
                }
            ],
        }
    )
    client = Mock()
    client.converse.side_effect = [_response(invalid_item_text), _response(invalid_item_text)]
    provider = BedrockProvider(client=client)

    with pytest.raises(BedrockOutputError):
        await provider.extract_text_transactions("oi")

    assert client.converse.call_count == 2
