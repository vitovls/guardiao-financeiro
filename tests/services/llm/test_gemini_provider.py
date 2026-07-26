import json
from unittest.mock import Mock

from services.llm.gemini_provider import GeminiProvider


def _mock_client(response_text: str) -> Mock:
    client = Mock()
    client.models.generate_content.return_value = Mock(text=response_text)
    return client


async def test_extract_text_transactions_returns_transacoes_when_present():
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
    provider = GeminiProvider(client=client)

    result = await provider.extract_text_transactions("gastei 30 no mercado")

    assert len(result) == 1
    assert result[0].descricao == "mercado"
    assert result[0].valor == 30.0


async def test_extract_text_transactions_returns_empty_when_not_transacao():
    response_text = json.dumps({"e_transacao": False, "transacoes": []})
    client = _mock_client(response_text)
    provider = GeminiProvider(client=client)

    result = await provider.extract_text_transactions("oi tudo bem?")

    assert result == []


async def test_extract_document_transactions_image_jpeg_returns_transacoes_and_prompt_mentions_imagem():
    response_text = json.dumps(
        [
            {
                "data": "2026-07-26",
                "descricao": "padaria",
                "valor": 15.0,
                "tipo": "saida",
                "categoria": "alimentacao",
            }
        ]
    )
    client = _mock_client(response_text)
    provider = GeminiProvider(client=client)

    result = await provider.extract_document_transactions(b"fake-bytes", "image/jpeg")

    assert len(result) == 1
    assert result[0].descricao == "padaria"
    call_kwargs = client.models.generate_content.call_args.kwargs
    prompt_text = call_kwargs["contents"][1]
    assert "imagem" in prompt_text


async def test_extract_document_transactions_pdf_prompt_mentions_pdf():
    response_text = json.dumps([])
    client = _mock_client(response_text)
    provider = GeminiProvider(client=client)

    await provider.extract_document_transactions(b"fake-bytes", "application/pdf")

    call_kwargs = client.models.generate_content.call_args.kwargs
    prompt_text = call_kwargs["contents"][1]
    assert "PDF" in prompt_text
