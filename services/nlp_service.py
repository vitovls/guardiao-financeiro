import json
from datetime import date

from google import genai
from google.genai import types

from models import Transacao
from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_text_transference(txt: str) -> list[Transacao]:
    today = date.today().isoformat()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            f'A data de hoje é {today}. O usuário escreveu: "{txt}". '
            'Responda APENAS com JSON neste formato: '
            '{"e_transacao": true|false, "transacoes": [{"data": "", "descricao": "", '
            '"valor": 0.0, "tipo": "entrada|saida", "categoria": ""}]}. '
            'Marque "e_transacao" como false se a mensagem não descrever um gasto ou '
            'recebimento (ex: saudação, pergunta, conversa solta). Nesse caso, '
            '"transacoes" deve ser uma lista vazia. '
            "Se não houver data explícita na mensagem, use a data de hoje."
        ),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    dados = json.loads(response.text)

    if not dados.get("e_transacao"):
        return []

    return [Transacao(**item) for item in dados["transacoes"]]
