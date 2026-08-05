import json
from datetime import date
from unittest.mock import Mock

from services.llm.gemini_provider import GeminiProvider


def _mock_client(response_text: str) -> Mock:
    client = Mock()
    client.models.generate_content.return_value = Mock(text=response_text)
    return client


async def test_interpret_text_returns_transacao_intent_when_present():
    response_text = json.dumps(
        {
            "intencao": "transacao",
            "transacoes": [
                {
                    "data": "2026-07-26",
                    "descricao": "mercado",
                    "valor": 30.0,
                    "tipo": "saida",
                    "categoria": "alimentacao",
                }
            ],
            "periodo_inicio": None,
            "periodo_fim": None,
            "categoria": None,
        }
    )
    client = _mock_client(response_text)
    provider = GeminiProvider(client=client)

    result = await provider.interpret_text("gastei 30 no mercado")

    assert result.intencao == "transacao"
    assert result.transacoes[0].descricao == "mercado"


async def test_interpret_text_returns_nenhuma_intent():
    response_text = json.dumps(
        {
            "intencao": "nenhuma",
            "transacoes": [],
            "periodo_inicio": None,
            "periodo_fim": None,
            "categoria": None,
        }
    )
    client = _mock_client(response_text)
    provider = GeminiProvider(client=client)

    result = await provider.interpret_text("oi tudo bem?")

    assert result.intencao == "nenhuma"
    assert result.transacoes == []


async def test_interpret_text_returns_consulta_intent_with_periodo():
    response_text = json.dumps(
        {
            "intencao": "consulta",
            "transacoes": [],
            "periodo_inicio": "2026-07-01",
            "periodo_fim": "2026-07-31",
            "categoria": None,
        }
    )
    client = _mock_client(response_text)
    provider = GeminiProvider(client=client)

    result = await provider.interpret_text("quanto gastei esse mês?")

    assert result.periodo_inicio == date(2026, 7, 1)
    assert result.periodo_fim == date(2026, 7, 31)


async def test_interpret_text_returns_consulta_intent_with_categoria():
    response_text = json.dumps(
        {
            "intencao": "consulta",
            "transacoes": [],
            "periodo_inicio": "2026-07-01",
            "periodo_fim": "2026-07-31",
            "categoria": "mercado",
        }
    )
    client = _mock_client(response_text)
    provider = GeminiProvider(client=client)

    result = await provider.interpret_text("quanto gastei em mercado esse mês?")

    assert result.categoria == "mercado"


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
