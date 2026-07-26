---
type: TASKS
version: 1.0.0
author: Victor Veloso
date: 2026-07-26
status: Approved
spec:
plan:
inv: INV002
---

# TASKS004 — Gemini → Bedrock (Fase 1 do plano de migração)

## Contexto

Diagnóstico completo em `docs/analysis/INV002-gemini-para-bedrock.md`. Resumo: `services/nlp_service.py` e `services/ocr_service.py` chamam `google-genai` direto, sem nenhuma abstração de provedor. Fase 0 (fundação AWS) concluída — `boto3==1.43.56` instalado, credenciais funcionando, inference profiles confirmados (`us.amazon.nova-micro-v1:0`, `us.amazon.nova-lite-v1:0`, região `us-east-2`).

Esta task **não toca `handlers/`, `repository/`, `database/` nem `models.py`**. Handlers continuam chamando `extract_text_transactions(text)` e `extract_photo_data(path)` exatamente como hoje — a troca de provedor acontece inteiramente dentro de `services/`.

Branch: `feat/bedrock-provider` (criar antes de qualquer código, conforme `CLAUDE.md`).

## Decisão de Design

1. **Novo subpacote `services/llm/`** (sem `__init__.py`, seguindo o padrão do projeto — `services/`, `handlers/`, `repository/` também não usam `__init__.py`, são pacotes de namespace implícitos):
   - `services/llm/provider.py` — `LLMProvider` (ABC) + exceções (`LLMProviderError`, `BedrockOutputError`).
   - `services/llm/gemini_provider.py` — `GeminiProvider`.
   - `services/llm/bedrock_provider.py` — `BedrockProvider`.
   - `services/llm/factory.py` — `get_llm_provider()`.
2. **Assinatura da interface usa `list[Transacao]`** em ambos os métodos (não `Transacao` singular, apesar do `plano-contexto.md` sugerir isso — CLAUDE.md manda `list[Transacao]` como retorno padrão entre camadas):
   ```python
   class LLMProvider(ABC):
       async def extract_text_transactions(self, text: str) -> list[Transacao]: ...
       async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]: ...
   ```
3. **`ABC` é justificado aqui** (diferente da regra do CLAUDE.md para `repository/`) porque há duas implementações reais desde o primeiro commit desta task: `GeminiProvider` e `BedrockProvider`.
4. **Providers recebem o client injetável no construtor** (`def __init__(self, client=None)`), para permitir mock em teste sem monkeypatch de módulo. Se `client` não for passado, cada provider cria o seu (`genai.Client(...)` / `boto3.client("bedrock-runtime", ...)`).
5. **Erro tratado, nunca exceção vazando pro handler:** `nlp_service.py`/`ocr_service.py` envolvem a chamada ao provider em `try/except Exception`, logam (`print(..., file=sys.stderr)` — não existe `logging` configurado no projeto hoje, e configurá-lo é fora de escopo) e retornam `[]` em caso de erro não recuperável. Isso reaproveita as mensagens amigáveis que **já existem** e não mudam: `handlers/text_handler.py:15` ("Não foi identificada nenhuma transação...") e `services/message_service.py:27` ("Não encontrei nenhuma transação nessa imagem."). Não é necessário criar nenhuma mensagem nova nem tocar handlers/message_service.
6. **Prompts completos viram funções em `prompts.py`** (não só o `TRANSACTION_SCHEMA`, que já existe e não muda):
   ```python
   def build_text_extraction_prompt(today: str, text: str) -> str: ...
   def build_document_extraction_prompt(document_label: str) -> str: ...
   ```
   Funções (não constantes com `.format()`) para evitar colisão de chaves `{}` entre o template e o JSON literal do `TRANSACTION_SCHEMA` embutido.
7. **Mapeamento mime → rótulo/format é responsabilidade de cada provider**, não de `prompts.py` nem de `ocr_service.py`:
   - Gemini usa o rótulo só para a redação do prompt (`"imagem"` ou `"PDF"`).
   - Bedrock usa o mime para escolher o tipo de content block da Converse API (`image` vs `document`) — ver T5.
8. **Bedrock Converse API — dois tipos de content block, confirmados em `docs.aws.amazon.com/bedrock/latest/APIReference/API_runtime_DocumentBlock.html`:**
   - `image/jpeg` → `{"image": {"format": "jpeg", "source": {"bytes": file_bytes}}}`.
   - `application/pdf` → `{"document": {"format": "pdf", "name": "extrato bancario", "source": {"bytes": file_bytes}}}`. O campo `name` é obrigatório, 1-200 caracteres, só alfanumérico + um espaço em sequência + hífen/parênteses/colchetes — **nunca derivar de nome de arquivo do usuário** (a própria doc da AWS alerta que é vetor de prompt injection). Usar sempre a constante literal `"extrato bancario"` (sem acento, por segurança de charset).
9. **Retry interno ao `BedrockProvider`**, espelhando os valores do Step Functions do template (`docs/guardiao-financeiro-stack.yml:155-162`): até 3 tentativas totais, intervalo base 1s, `BackoffRate=2` (teto dobra a cada tentativa: 1s → 2s → 4s), jitter FULL = `random.uniform(0, teto)` antes de cada espera, usando `asyncio.sleep` (não `time.sleep`, para não bloquear o event loop durante a espera — a chamada de rede em si via `boto3` é síncrona/bloqueante mesmo, isso é uma limitação conhecida e aceita, fora de escopo resolver aqui). Só `ThrottlingException` (via `botocore.exceptions.ClientError`, `error.response["Error"]["Code"]`) e timeout de rede (`botocore.exceptions.ConnectTimeoutError`/`ReadTimeoutError`) entram nessa política. `ValidationException` e qualquer outro `ClientError` propagam imediatamente, sem retry (erro de request, não transiente) — capturados pelo `except Exception` da decisão 5.
10. **Malformada a saída (JSON inválido, chaves ausentes, ou falha de validação Pydantic ao construir `Transacao`) → uma única re-tentativa extra** da chamada completa (não entra na política de retry do item 9 — é uma tentativa isolada, mesmo prompt). Se a segunda tentativa também falhar, `BedrockProvider` levanta `BedrockOutputError` (definida em `services/llm/provider.py`), capturada pelo `except Exception` da decisão 5.
11. **Flag `LLM_PROVIDER=gemini|bedrock`** em `run_polling/config.py`, lida com `os.getenv("LLM_PROVIDER", "gemini")` — mesmo estilo simples já usado para `BOT_TOKEN`/`GEMINI_API_KEY`, sem validação extra. Valor não reconhecido (nem `"gemini"` nem `"bedrock"`) → `get_llm_provider()` levanta `ValueError` na inicialização (falha rápido e visível, não silenciosamente cai para um default errado).
12. **Testes: pytest + pytest-asyncio, decidido nesta task** (ver T1). Primeira introdução de test runner no projeto — atualiza `CLAUDE.md` (seção "Testes") e `docs/PATTERNS.md` ("Decisões Estabelecidas"), porque é uma escolha que qualquer task futura vai herdar.
13. **Decisão que a Fase 3 vai herdar:** o padrão "interface de provedor + factory lendo flag de ambiente + provider concreto testável via client injetado" é o mesmo que `DB_BACKEND=sqlite|dynamo` vai seguir (`plano-contexto.md:170`). Registrado em `PATTERNS.md` (ver T9).

---

## Progresso

- [x] T1 — Configurar pytest + pytest-asyncio
- [x] T2 — Interface `LLMProvider` + exceções
- [x] T3 — `prompts.py`: prompts completos como funções
- [x] T4 — `GeminiProvider` (refactor sem mudança de comportamento)
- [x] T5 — `BedrockProvider`: content blocks + chamada Converse + parse/validação (sem retry)
- [x] T6 — `BedrockProvider`: retry com backoff+jitter (throttling/timeout)
- [x] T7 — `BedrockProvider`: re-tentativa de output malformado
- [x] T8 — Factory `get_llm_provider()` + flag `LLM_PROVIDER`
- [x] T9 — Refatorar `nlp_service.py`/`ocr_service.py` para delegar ao provider + broadcast em `PATTERNS.md`/`CLAUDE.md`

---

## Ordem de Execução

T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9

(T4 depende de T2+T3. T5-T7 são incrementais sobre o mesmo arquivo `bedrock_provider.py` e dependem de T2+T3. T8 depende de T4+T7. T9 depende de T8 — é a última, pois é o "fio" que liga tudo ao restante do sistema já existente.)

---

## T1 — Configurar pytest + pytest-asyncio

**O quê:** primeira introdução de test runner no projeto.

- Adicionar a `requirements.txt`: `pytest==9.1.1`, `pytest-asyncio==1.4.0` (já instaladas no venv local — só faltam pinadas no arquivo).
- Criar `pytest.ini` na raiz:
  ```ini
  [pytest]
  asyncio_mode = auto
  ```
- Criar pasta `tests/services/llm/` (mirror de `services/llm/`), sem `__init__.py` (mesmo padrão do resto do projeto).
- `CLAUDE.md` (seção "Testes") e `docs/PATTERNS.md` ("Decisões Estabelecidas") **já foram atualizados** nesta rodada de `/map-task` — nenhuma edição adicional necessária nesses dois arquivos, só confirmar que `pytest` de fato funciona como descrito neles.

**Critério de aceitação:** `pytest` roda na raiz do projeto sem erro (mesmo sem nenhum teste ainda, deve reportar "no tests ran" / 0 coletados, não erro de configuração).

---

## T2 — Interface `LLMProvider` + exceções

**Depois** (`services/llm/provider.py`, arquivo novo):
```python
from abc import ABC, abstractmethod

from models import Transacao


class LLMProviderError(Exception):
    """Erro genérico de provider de LLM, tratado pelos services (nunca vaza ao handler)."""


class BedrockOutputError(LLMProviderError):
    """Bedrock retornou JSON inválido/vazio mesmo após a re-tentativa de output malformado."""


class LLMProvider(ABC):
    @abstractmethod
    async def extract_text_transactions(self, text: str) -> list[Transacao]:
        ...

    @abstractmethod
    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        ...
```

**Teste** (`tests/services/llm/test_provider.py`): instanciar uma subclasse concreta mínima que implementa os dois métodos e confirmar que consegue ser instanciada; confirmar que instanciar `LLMProvider` diretamente levanta `TypeError` (comportamento padrão de `ABC` com `@abstractmethod`).

---

## T3 — `prompts.py`: prompts completos como funções

**Antes** (`prompts.py`, arquivo completo atual):
```python
TRANSACTION_SCHEMA = (
    '[{"data": "YYYY-MM-DD", "descricao": "", "valor": 0.0, "tipo": "entrada|saida", "categoria": ""}]'
)
```

**Depois** (acrescentar ao mesmo arquivo, `TRANSACTION_SCHEMA` não muda):
```python
def build_text_extraction_prompt(today: str, text: str) -> str:
    return (
        f'A data de hoje é {today}. O usuário escreveu: "{text}". '
        f'Responda APENAS com JSON neste formato: {{"e_transacao": true|false, "transacoes": {TRANSACTION_SCHEMA}}}. '
        'Marque "e_transacao" como false se a mensagem não descrever um gasto ou '
        'recebimento (ex: saudação, pergunta, conversa solta). Nesse caso, '
        '"transacoes" deve ser uma lista vazia. '
        "Se não houver data explícita na mensagem, use a data de hoje."
    )


def build_document_extraction_prompt(document_label: str) -> str:
    return (
        f"Extraia as transações deste(a) {document_label} de extrato bancário. "
        f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"
    )
```

**Teste** (`tests/test_prompts.py`): `build_text_extraction_prompt("2026-07-26", "gastei 30 no mercado")` contém a data, o texto do usuário, e a palavra `"e_transacao"`. `build_document_extraction_prompt("imagem")` contém `"imagem"` e o `TRANSACTION_SCHEMA` literal.

---

## T4 — `GeminiProvider` (refactor sem mudança de comportamento)

**Antes:** ver `services/nlp_service.py` e `services/ocr_service.py` completos em `INV002`, seção "Estado Atual".

**Depois** (`services/llm/gemini_provider.py`, arquivo novo):
```python
import json
from datetime import date

from google import genai
from google.genai import types

from models import Transacao
from prompts import build_document_extraction_prompt, build_text_extraction_prompt
from run_polling.config import GEMINI_API_KEY
from services.llm.provider import LLMProvider

_MIME_TO_LABEL = {"image/jpeg": "imagem", "application/pdf": "PDF"}
_MODEL = "gemini-2.5-flash"


class GeminiProvider(LLMProvider):
    def __init__(self, client=None):
        self._client = client or genai.Client(api_key=GEMINI_API_KEY)

    async def extract_text_transactions(self, text: str) -> list[Transacao]:
        prompt = build_text_extraction_prompt(date.today().isoformat(), text)
        response = self._client.models.generate_content(
            model=_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        response_data = json.loads(response.text)
        if not response_data.get("e_transacao"):
            return []
        return [Transacao(**item) for item in response_data["transacoes"]]

    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        label = _MIME_TO_LABEL.get(mime_type, "documento")
        prompt = build_document_extraction_prompt(label)
        response = self._client.models.generate_content(
            model=_MODEL,
            contents=[types.Part.from_bytes(data=file_bytes, mime_type=mime_type), prompt],
            config=types.GenerateContentConfig(response_mime_type="application/json"),
        )
        response_data = json.loads(response.text)
        return [Transacao(**item) for item in response_data]
```

**Teste** (`tests/services/llm/test_gemini_provider.py`), client mockado (`unittest.mock.Mock`, sem chamar a API real):
- `extract_text_transactions`: response mockada com `{"e_transacao": true, "transacoes": [{...um item válido...}]}` → retorna lista com 1 `Transacao`.
- `extract_text_transactions`: response mockada com `{"e_transacao": false, "transacoes": []}` → retorna `[]`.
- `extract_document_transactions` com `mime_type="image/jpeg"`: response mockada com lista de itens → retorna lista de `Transacao`; confirmar que o prompt passado ao client contém `"imagem"`.
- `extract_document_transactions` com `mime_type="application/pdf"`: confirmar que o prompt contém `"PDF"`.

**Regressão:** este T não muda comportamento observável — os testes acima validam que `GeminiProvider` produz exatamente os mesmos resultados que o `nlp_service.py`/`ocr_service.py` atuais produziriam para as mesmas entradas.

---

## T5 — `BedrockProvider`: content blocks + Converse + parse/validação (sem retry ainda)

**Depois** (`services/llm/bedrock_provider.py`, arquivo novo — versão sem retry, T6/T7 acrescentam):
```python
import json
from datetime import date

import boto3

from models import Transacao
from prompts import build_document_extraction_prompt, build_text_extraction_prompt
from services.llm.provider import LLMProvider

REGION = "us-east-2"
TEXT_MODEL_ID = "us.amazon.nova-micro-v1:0"
DOCUMENT_MODEL_ID = "us.amazon.nova-lite-v1:0"

_MIME_TO_IMAGE_FORMAT = {"image/jpeg": "jpeg"}
_MIME_TO_DOCUMENT_FORMAT = {"application/pdf": "pdf"}
_DOCUMENT_NAME = "extrato bancario"


class BedrockProvider(LLMProvider):
    def __init__(self, client=None):
        self._client = client or boto3.client("bedrock-runtime", region_name=REGION)

    async def extract_text_transactions(self, text: str) -> list[Transacao]:
        prompt = build_text_extraction_prompt(date.today().isoformat(), text)
        messages = [{"role": "user", "content": [{"text": prompt}]}]
        response_data = await self._call_and_parse(TEXT_MODEL_ID, messages)
        if not response_data.get("e_transacao"):
            return []
        return [Transacao(**item) for item in response_data["transacoes"]]

    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        label = "PDF" if mime_type in _MIME_TO_DOCUMENT_FORMAT else "imagem"
        prompt = build_document_extraction_prompt(label)
        content_block = self._build_content_block(file_bytes, mime_type)
        messages = [{"role": "user", "content": [content_block, {"text": prompt}]}]
        response_data = await self._call_and_parse(DOCUMENT_MODEL_ID, messages)
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

    async def _call_and_parse(self, model_id: str, messages: list[dict]) -> dict:
        response = self._client.converse(modelId=model_id, messages=messages)
        text = response["output"]["message"]["content"][0]["text"]
        return json.loads(text)
```

**Teste** (`tests/services/llm/test_bedrock_provider.py`), client mockado:
- `extract_text_transactions`: client mockado retornando o shape de `converse()` com texto JSON válido → retorna lista de `Transacao` correta; confirmar que `client.converse` foi chamado com `modelId=TEXT_MODEL_ID` e `messages[0]["content"][0]["text"]` contendo o prompt esperado.
- `extract_document_transactions` com `mime_type="image/jpeg"`: confirmar que o content block enviado é `{"image": {"format": "jpeg", "source": {"bytes": ...}}}`.
- `extract_document_transactions` com `mime_type="application/pdf"`: confirmar que o content block é `{"document": {"format": "pdf", "name": "extrato bancario", "source": {"bytes": ...}}}`.
- `mime_type` não suportado (ex: `"image/png"`) → levanta `ValueError`.

---

## T6 — `BedrockProvider`: retry com backoff+jitter (throttling/timeout)

**O quê:** envolver a chamada `self._client.converse(...)` de `_call_and_parse` numa política de retry.

**Depois** (substitui a linha `response = self._client.converse(...)` de T5):
```python
import asyncio
import random

from botocore.exceptions import ClientError, ConnectTimeoutError, ReadTimeoutError

_MAX_ATTEMPTS = 3
_BASE_INTERVAL_SECONDS = 1
_BACKOFF_RATE = 2
_RETRYABLE_ERROR_CODES = {"ThrottlingException"}


async def _converse_with_retry(client, model_id: str, messages: list[dict]) -> str:
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.converse(modelId=model_id, messages=messages)
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
```
(`_call_and_parse` passa a chamar `text = await _converse_with_retry(self._client, model_id, messages)` em vez de chamar `self._client.converse` direto.)

**Critério de aceitação — comportamento, não a forma exata do código acima (a função pode ficar como método privado da classe em vez de função de módulo, à escolha do implementador):**
- `ThrottlingException` na 1ª e 2ª chamada, sucesso na 3ª → retorna o resultado da 3ª chamada, `client.converse` foi chamado exatamente 3 vezes.
- `ThrottlingException` nas 3 chamadas → propaga a exceção (não engole o erro).
- `ValidationException` (qualquer `ClientError` com código fora de `_RETRYABLE_ERROR_CODES`) na 1ª chamada → propaga imediatamente, `client.converse` foi chamado só 1 vez (nunca tenta de novo).
- Nos testes, mockar `asyncio.sleep` (ex: `unittest.mock.patch("services.llm.bedrock_provider.asyncio.sleep")`) para o teste não esperar segundos de verdade.

---

## T7 — `BedrockProvider`: re-tentativa de output malformado

**O quê:** se o texto retornado não for JSON válido (ou faltar uma chave esperada, ou a validação Pydantic do `Transacao` falhar), tentar a chamada completa (Converse + parse, já com a política de retry de T6 dentro) mais uma vez. Se a segunda tentativa também falhar, levantar `BedrockOutputError`.

**Depois** (`_call_and_parse` de T5, revisado):
```python
async def _call_and_parse(self, model_id: str, messages: list[dict]) -> dict:
    for attempt in range(2):
        text = await _converse_with_retry(self._client, model_id, messages)
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            if attempt == 1:
                raise BedrockOutputError("Bedrock retornou JSON inválido após re-tentativa")
```

Nota: a validação de `KeyError` (ex.: `response_data["transacoes"]` ausente) e de `pydantic.ValidationError` (ao construir `Transacao(**item)`) acontece em `extract_text_transactions`/`extract_document_transactions`, que chamam `_call_and_parse` — essas duas chamadas também precisam ficar dentro do mesmo laço de "tenta 2x, senão `BedrockOutputError`". Estrutura sugerida: mover a construção de `Transacao` e o `if not response_data.get("e_transacao")` para dentro de uma função auxiliar que é chamada dentro do mesmo `for attempt in range(2)`, capturando `(json.JSONDecodeError, KeyError, pydantic.ValidationError)` juntos.

**Teste** (`tests/services/llm/test_bedrock_provider.py`, continuação):
- `client.converse` retorna texto não-JSON na 1ª chamada, JSON válido na 2ª → retorna o resultado correto, `client.converse` foi chamado 2 vezes (contando as chamadas internas de T6 dentro de cada tentativa de T7 — total pode ser mais que 2 se T6 também retentar, mas o cenário aqui assume T6 sem throttling, então 2 chamadas totais).
- `client.converse` retorna texto não-JSON nas 2 tentativas → levanta `BedrockOutputError`.
- `client.converse` retorna JSON válido mas faltando a chave `"transacoes"` (para o método de texto) → mesmo comportamento de retry + `BedrockOutputError` se persistir.
- `client.converse` retorna JSON com um item que falha validação Pydantic (ex: `"tipo": "invalido"`) → mesmo comportamento.

---

## T8 — Factory `get_llm_provider()` + flag `LLM_PROVIDER`

**Antes** (`run_polling/config.py`, arquivo completo atual):
```python
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# MEU_USER_ID = int(os.getenv("MEU_TELEGRAM_ID"))
```

**Depois** (acrescentar):
```python
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
```

**Depois** (`services/llm/factory.py`, arquivo novo):
```python
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
```

**Teste** (`tests/services/llm/test_factory.py`), usando `monkeypatch.setattr` no módulo `run_polling.config` (ou `monkeypatch.setenv` + reload, à escolha do implementador — o que importar é o comportamento):
- `LLM_PROVIDER="gemini"` → `get_llm_provider()` retorna instância de `GeminiProvider`.
- `LLM_PROVIDER="bedrock"` → retorna instância de `BedrockProvider`.
- `LLM_PROVIDER="outro"` → levanta `ValueError`.

---

## T9 — Refatorar `nlp_service.py`/`ocr_service.py` para delegar ao provider

**Antes:** ver `INV002`, seção "Estado Atual" (código completo de ambos os arquivos hoje).

**Depois** (`services/nlp_service.py`, arquivo completo):
```python
import sys

from models import Transacao
from services.llm.factory import get_llm_provider
from services.llm.provider import LLMProviderError

_provider = get_llm_provider()


async def extract_text_transactions(text: str) -> list[Transacao]:
    try:
        return await _provider.extract_text_transactions(text)
    except (LLMProviderError, Exception) as exc:
        print(f"[nlp_service] falha ao extrair transação de texto: {exc}", file=sys.stderr)
        return []
```

**Depois** (`services/ocr_service.py`, arquivo completo):
```python
import sys

from models import Transacao
from services.llm.factory import get_llm_provider
from services.llm.provider import LLMProviderError

_provider = get_llm_provider()


async def extract_photo_data(image_path: str) -> list[Transacao]:
    with open(image_path, "rb") as f:
        file_bytes = f.read()

    if image_path.endswith(".jpg"):
        mime_type = "image/jpeg"
    elif image_path.endswith(".pdf"):
        mime_type = "application/pdf"
    else:
        raise ValueError(f"Formato não suportado: {image_path}")

    try:
        return await _provider.extract_document_transactions(file_bytes, mime_type)
    except (LLMProviderError, Exception) as exc:
        print(f"[ocr_service] falha ao extrair transação de documento: {exc}", file=sys.stderr)
        return []
```

Nota: `except (LLMProviderError, Exception)` é redundante em sintaxe (todo `LLMProviderError` já é `Exception`) — o objetivo é documentar a intenção (capturar tanto os erros tipados do provider quanto qualquer coisa inesperada); usar só `except Exception as exc:` é equivalente e mais limpo, à escolha do implementador.

`handlers/photo_handler.py`, `handlers/pdf_handler.py` e `handlers/text_handler.py` **permanecem byte-a-byte idênticos** — nenhuma edição nesses três arquivos.

**Teste** (`tests/services/test_nlp_service.py`, `tests/services/test_ocr_service.py`), com `get_llm_provider` mockado (ex.: `monkeypatch.setattr("services.nlp_service._provider", fake_provider)`):
- Provider mockado retorna lista de `Transacao` → `extract_text_transactions`/`extract_photo_data` repassam a mesma lista.
- Provider mockado levanta uma exceção qualquer → função retorna `[]` sem propagar.

**Cenários de Teste Manual** (rodar o bot de verdade, `python main.py`):
1. `LLM_PROVIDER=gemini` (ou variável ausente, testando o default) — enviar "Gastei 30 reais no mercado" por texto → resposta idêntica à de hoje (regressão).
2. `LLM_PROVIDER=gemini` — enviar uma foto de recibo/extrato → resposta idêntica à de hoje.
3. `LLM_PROVIDER=bedrock` — repetir os cenários 1 e 2 → resposta equivalente (mesma estrutura, valores extraídos corretos), usando Nova Micro/Nova Lite.
4. `LLM_PROVIDER=bedrock` — enviar um PDF de extrato → confirma que o content block `document` funciona de ponta a ponta (não só o `image` já validado no smoke test da Fase 0).
5. `LLM_PROVIDER=invalido` — bot deve falhar ao iniciar com `ValueError` claro, não silenciosamente cair para Gemini.

**Defeito encontrado no cenário 4 e corrigido:** PDF real com várias transações retornava `BedrockOutputError` ("Bedrock retornou JSON inválido após re-tentativa") nas duas tentativas. Causa raiz confirmada contra a API real: `converse()` sem `inferenceConfig` usa default de 2000 tokens de saída, truncando o JSON no meio do array para extratos com muitas transações. Corrigido em `bedrock_provider.py` (`_MAX_OUTPUT_TOKENS = 5000` passado em todo `converse()`), com teste automatizado (`test_extract_text_transactions_sets_max_tokens_to_avoid_truncation`) e teste manual real (chamada direta ao Bedrock confirmando truncamento em 2000 e ausência de erro em 5000/10000). Registrado em `docs/PATTERNS.md`.

**Broadcast:** já feito nesta rodada de `/map-task` — `docs/PATTERNS.md` já tem as entradas "Troca de provedor externo: interface + factory por flag de ambiente" e "Test runner do projeto: pytest + pytest-asyncio"; `CLAUDE.md` já tem a seção "Testes" atualizada. Nenhuma ação adicional aqui.

---

## Regra do Escoteiro / Testes

- Todo T de T2 a T9 sai com testes verdes (`pytest`) antes de avançar para o próximo — TDD: escrever o teste que falha primeiro, depois o código que faz passar.
- Nenhuma chamada real a Gemini ou Bedrock nos testes automatizados — sempre client mockado. As chamadas reais só acontecem nos "Cenários de Teste Manual" de T9, rodados manualmente pelo usuário.
- Se durante a implementação de T6/T7 ficar claro que a estrutura de retry proposta no "Depois" precisa mudar de forma (por exemplo, virar métodos da classe em vez de função de módulo), os critérios de aceitação (comportamento observável, contagem de chamadas ao client mockado) são o que importa — a forma exata do código é sugestão, não contrato.

---

## Fora de Escopo

- "Rodar em produção com `bedrock` e monitorar taxa de erro de extração" (`plano-contexto.md:255`) — ação operacional do usuário pós-merge, não gera código nesta task.
- Remover `google-genai`/`GEMINI_API_KEY` e o `GeminiProvider` (`plano-contexto.md:256`) — só depois de dias de estabilidade confirmada em produção; será uma task futura própria (Fase 1b/limpeza).
- Qualquer mudança em `handlers/`, `repository/`, `database/`, `models.py`, `main.py`.
- Introduzir `logging` estruturado (módulo `logging`, formatters, handlers) — mantido `print(..., file=sys.stderr)`, consistente com o resto do projeto hoje.
- Fase 2 (S3) e Fase 3 (DynamoDB) — fora do escopo desta fase, mesmo que a decisão 13 preveja reaproveitamento futuro.
