from datetime import date

from google import genai
from google.genai import types

from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)

async def extract_text_transference(txt: str) -> str:
    today = date.today().isoformat()
    
    response = client.models.generate_content(
      model="gemini-2.5-flash",
      contents=(
            f'A data de hoje é {today}. O usuário descreveu uma transação financeira '
            f'em linguagem natural: "{txt}". '
            'Extraia e responda APENAS com JSON: [{"data": "", "descricao": "", '
            '"valor": 0.0, "tipo": "entrada|saida", "categoria": ""}]. '
            "Se não houver data explícita na mensagem, use a data de hoje."
      ),
      config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    
    return response.text

