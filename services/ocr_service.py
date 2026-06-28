import json

from google import genai
from google.genai import types

from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_photo_data(caminho_imagem: str) -> str:
    with open(caminho_imagem, "rb") as f:
        file_bytes = f.read()
        
    if caminho_imagem.endswith(".jpg"):
        mime_type = "image/jpeg"
        prompt = "Extraia as transações desta imagem de extrato bancário. "
    elif caminho_imagem.endswith(".pdf"):
        mime_type = "application/pdf"
        prompt = "Extraia as transações desse pdf de extrato bancário. "
    else:
        raise ValueError(f"Formato não suportado: {caminho_imagem}")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            (
                prompt
                + 'Responda APENAS com JSON: [{"data": "", "descricao": "", '
                '"valor": 0.0, "tipo": "entrada|saida"}]'
            ),
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    return response.text


def formatter_message(json_str: str) -> str:
    try:
        transactions = json.loads(json_str)
    except json.JSONDecodeError:
        return "⚠️ Não consegui interpretar o extrato. Tenta mandar a foto novamente?"

    if not transactions:
        return "Não encontrei nenhuma transação nessa imagem."

    lines = ["<b>📊 Extrato processado</b>", ""]
    enter = 0.0
    leave = 0.0

    for t in transactions:
        emoji = "🟢" if t["tipo"] == "entrada" else "🔴"
        valor = t["valor"]
        if t["tipo"] == "entrada":
            enter += valor
        else:
            leave += valor
        lines.append(f"{emoji} {t['data']} — {t['descricao']}: R$ {valor:.2f}")

    balance = enter - leave
    lines.append("")
    lines.append("<b>Resumo</b>")
    lines.append(f"🟢 Entradas: R$ {enter:.2f}")
    lines.append(f"🔴 Saídas: R$ {leave:.2f}")
    lines.append(f"💰 Saldo: R$ {balance:.2f}")

    return "\n".join(lines)
