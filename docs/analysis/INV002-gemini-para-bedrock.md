---
type: INV
version: 1.0.0
author: Victor Veloso
date: 2026-07-26
status: Draft
---

# INV002 — Gemini → Bedrock (Fase 1 do plano de migração)

## Contexto

Gatilho: `docs/analysis/plano-contexto.md`, seção "Fase 1 — Trocar Gemini por Bedrock (dentro do monólito)" (linhas 127-146) e "Lista de tarefas / Fase 1" (linhas 246-256). Fase 0 (fundação AWS) está concluída — `docs/tasks/TASKS003-fundacao-aws.md`, status "Concluído": `boto3==1.43.56` instalado, credenciais via profile `guardiao-dev`, smoke test rodando com sucesso (`scripts/smoke_test_bedrock.py`).

Branch: nenhuma criada ainda para esta fase — será `feat/bedrock-provider` (convenção CLAUDE.md, seção "Branches").

Esta INV mapeia a troca do "cérebro" (LLM) do bot, mantendo monólito, polling, SQLite e disco local intocados — só os dois pontos de chamada de IA (`services/nlp_service.py`, `services/ocr_service.py`) mudam de fornecedor por trás de uma interface e de uma flag de ambiente.

## Estado Atual (Antes)

### `services/nlp_service.py` — texto → transação

```python
import json
from datetime import date

from google import genai
from google.genai import types

from models import Transacao
from prompts import TRANSACTION_SCHEMA
from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_text_transactions(text: str) -> list[Transacao]:
    today = date.today().isoformat()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            f'A data de hoje é {today}. O usuário escreveu: "{text}". '
            f'Responda APENAS com JSON neste formato: {{"e_transacao": true|false, "transacoes": {TRANSACTION_SCHEMA}}}. '
            'Marque "e_transacao" como false se a mensagem não descrever um gasto ou '
            'recebimento (ex: saudação, pergunta, conversa solta). Nesse caso, '
            '"transacoes" deve ser uma lista vazia. '
            "Se não houver data explícita na mensagem, use a data de hoje."
        ),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    response_data = json.loads(response.text)

    if not response_data.get("e_transacao"):
        return []

    return [Transacao(**item) for item in response_data["transacoes"]]
```

Chamador: `handlers/text_handler.py:12` — `transactions = await extract_text_transactions(text)`.

### `services/ocr_service.py` — imagem/PDF → transação

```python
import json

from google import genai
from google.genai import types

from models import Transacao
from prompts import TRANSACTION_SCHEMA
from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_photo_data(image_path: str) -> list[Transacao]:
    with open(image_path, "rb") as f:
        file_bytes = f.read()

    if image_path.endswith(".jpg"):
        mime_type = "image/jpeg"
        prompt = "Extraia as transações desta imagem de extrato bancário. "
    elif image_path.endswith(".pdf"):
        mime_type = "application/pdf"
        prompt = "Extraia as transações desse pdf de extrato bancário. "
    else:
        raise ValueError(f"Formato não suportado: {image_path}")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            (prompt + f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"),
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    response_data = json.loads(response.text)
    return [Transacao(**item) for item in response_data]
```

Chamadores: `handlers/photo_handler.py:17` e `handlers/pdf_handler.py:19` — ambos `transactions = await extract_photo_data(path)`, onde `path` é um arquivo em `fotos/` baixado do Telegram.

### `prompts.py` (arquivo completo — 3 linhas)

```python
TRANSACTION_SCHEMA = (
    '[{"data": "YYYY-MM-DD", "descricao": "", "valor": 0.0, "tipo": "entrada|saida", "categoria": ""}]'
)
```

Único ponto de definição do schema JSON — hoje só usado por `nlp_service.py` e `ocr_service.py`, embutido dentro de uma string de prompt maior em cada um.

### `models.py` (arquivo completo)

```python
from datetime import date
from typing import Literal

from pydantic import BaseModel


class Transacao(BaseModel):
    data: date
    descricao: str
    valor: float
    tipo: Literal["entrada", "saida"]
    categoria: str = ""
```

### `run_polling/config.py` (arquivo completo)

```python
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# MEU_USER_ID = int(os.getenv("MEU_TELEGRAM_ID"))
```

Único ponto de leitura de variáveis de ambiente da aplicação — `LLM_PROVIDER` entra aqui.

### `scripts/smoke_test_bedrock.py` (referência já validada na Fase 0)

Confirma os IDs de modelo corretos e a API a usar:

```python
REGION = os.getenv("AWS_REGION", "us-east-2")
TEXT_MODEL_ID = "us.amazon.nova-micro-v1:0"
IMAGE_MODEL_ID = "us.amazon.nova-lite-v1:0"
...
client = boto3.client("bedrock-runtime", region_name=REGION)
client.converse(modelId=TEXT_MODEL_ID, messages=[{"role": "user", "content": [{"text": "..."}]}])
client.converse(modelId=IMAGE_MODEL_ID, messages=[{"role": "user", "content": [
    {"image": {"format": "png", "source": {"bytes": image_bytes}}},
    {"text": "..."},
]}])
```

`response["output"]["message"]["content"][0]["text"]` é onde o texto de resposta vem — o `BedrockProvider` terá que fazer `json.loads` nesse texto (Converse API não tem um `response_mime_type=json` nativo como o `google-genai`; o JSON precisa ser pedido no prompt e extraído do campo de texto, igual ao padrão hoje usado pelo Gemini).

## Análise de Causa Raiz / Motivação

Não é bug — é troca de dependência planejada (`docs/analysis/plano-contexto.md`, seção 1 "Limitações que motivam a migração"): Gemini é uma dependência externa fora do ecossistema AWS; o alvo da migração serverless (Step Functions + Bedrock) exige que o "cérebro" já fale com Bedrock antes de Fases futuras (S3, DynamoDB, webhook) desmontarem o monólito.

Hoje `nlp_service.py` e `ocr_service.py` chamam o SDK `google-genai` diretamente — não existe nenhuma camada de abstração entre "extrair transação" e "qual provedor de IA faz isso". Trocar de provedor hoje significa reescrever os dois arquivos inteiros.

## Hipóteses de Solução (confirmadas contra CLAUDE.md e as respostas do usuário)

Estas não são "descobertas" de bug — são decisões de design já fechadas nesta investigação, registradas aqui porque a rota escolhida é curta (ver `Classificação`) e elas substituem a seção "Decisão de Design" que normalmente viria de um PLN.

1. **Assinatura da interface usa `list[Transacao]`, não `Transacao` singular.** O `plano-contexto.md` (linha 131) propõe `extrair_transacao_de_texto(texto) -> Transacao` — mas isso contradiz CLAUDE.md ("O que Sempre Fazer": `list[Transacao]` como tipo de retorno padrão entre camadas) e as duas funções atuais já retornam `list[Transacao]` (uma mensagem de texto pode conter múltiplas transações; um extrato também). **Decisão: a interface usa `list[Transacao]` em ambos os métodos, ignorando a assinatura singular do plano de migração.**

2. **`ocr_service.py` e `nlp_service.py` continuam sendo os únicos arquivos que "sabem" que existe uma chamada de IA — os handlers não mudam.** CLAUDE.md proíbe chamar Gemini (e, por extensão, qualquer LLM) fora desses dois arquivos. Portanto o provider é selecionado *dentro* de `nlp_service.py`/`ocr_service.py`, que passam a delegar para `LLMProvider` em vez de chamar `google-genai` diretamente. `handlers/text_handler.py`, `photo_handler.py` e `pdf_handler.py` **não mudam uma linha** — continuam chamando `extract_text_transactions(text)` e `extract_photo_data(path)` como hoje.

3. **Leitura de arquivo e detecção de mime type continuam em `ocr_service.py`.** O provider recebe `bytes` + `mime_type` prontos (não um path) — isso já prepara o terreno para a Fase 2 (S3), onde o arquivo pode vir de outro lugar que não seja disco local, sem mexer no provider de novo. `ocr_service.extract_photo_data(image_path)` mantém a lógica atual de `if image_path.endswith(".jpg")/.pdf` para decidir `mime_type`, lê os bytes, e repassa para `provider.extract_document_transactions(file_bytes, mime_type)`.

4. **Localização dos novos arquivos (confirmado pelo usuário): novo subpacote `services/llm/`.**
   - `services/llm/provider.py` — classe abstrata `LLMProvider` (ABC, porque haverá duas implementações reais — Gemini e Bedrock — o que satisfaz a exceção da regra "Nunca adicionar Protocol/ABC sem uma segunda implementação real", que no CLAUDE.md é escrita para `repository/` mas o princípio se aplica igual aqui).
   - `services/llm/gemini_provider.py` — `GeminiProvider`, código movido de `nlp_service.py`/`ocr_service.py` sem mudança de comportamento.
   - `services/llm/bedrock_provider.py` — `BedrockProvider`, implementação nova via Converse API.
   - `services/nlp_service.py` e `services/ocr_service.py` passam a importar de `services/llm/` e delegar, mantendo suas assinaturas públicas atuais.

5. **Assinatura da interface (nomes em inglês, por CLAUDE.md):**
   ```python
   class LLMProvider(ABC):
       async def extract_text_transactions(self, text: str) -> list[Transacao]: ...
       async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]: ...
   ```
   `extract_document_transactions` cobre tanto imagem quanto PDF (ambos hoje passam pela mesma função `extract_photo_data`, ambos vão para Nova Lite do lado Bedrock).

6. **Retry: interno ao `BedrockProvider` (confirmado pelo usuário), sem utilitário compartilhado.** `GeminiProvider` não precisa — o SDK `google-genai` não expõe as mesmas exceções de throttling que o `boto3`/Bedrock, e não há indício de necessidade de retry nele hoje (fora de escopo introduzir).

7. **Fórmula exata do backoff+jitter, para não deixar "exponencial com jitter" subespecificado:** espelhar os valores já usados no Step Functions do template (`docs/guardiao-financeiro-stack.yml:155-162`): `IntervalSeconds: 1`, `MaxAttempts: 3`, `BackoffRate: 2`, `JitterStrategy: FULL`. Jitter FULL é `sleep = random.uniform(0, min(cap, base * (backoff_rate ** attempt)))` — não é "media" nem "decorrelated" jitter. Traduzindo para o `BedrockProvider`: até 3 tentativas totais (1 chamada + 2 retries), intervalo base 1s, dobrando a cada tentativa (1s → 2s → 4s de teto), sorteando um valor uniforme entre 0 e esse teto antes de cada espera.

8. **Erros do Bedrock a tratar especificamente** (`docs/analysis/plano-contexto.md:136-140`, já é lista fechada, sem ambiguidade):
   - `ThrottlingException` → retry com a política do item 7.
   - `ValidationException` / payload rejeitado → log detalhado + mensagem amigável ao usuário, sem retry (erro de request, não transiente).
   - Timeout de rede (`botocore.exceptions.ConnectTimeoutError`/`ReadTimeoutError`) → mesma política de retry do item 7.
   - Resposta vazia ou JSON inválido do modelo (falha ao `json.loads` o texto de saída, ou validação Pydantic do `Transacao` falhando) → **uma única re-tentativa com o mesmo prompt** (não entra na mesma política de 3 tentativas do item 7 — é uma tentativa extra e separada); se ainda assim falhar, propagar um erro tratado para o service informar o usuário ("não consegui entender essa mensagem/imagem, tenta de novo").

9. **`prompts.py` — fonte única do schema, adaptada para os dois wire formats.** Hoje o schema (`TRANSACTION_SCHEMA`) já é uma constante compartilhada, mas embutida em strings de prompt diferentes em cada service. Decisão: mover os textos de prompt completos (o que hoje está inline em `nlp_service.py`/`ocr_service.py`) para `prompts.py` como constantes (`TEXT_EXTRACTION_PROMPT`, `DOCUMENT_EXTRACTION_PROMPT` ou nomes equivalentes, com `{today}` como placeholder via `.format()`/f-string), para que `GeminiProvider` e `BedrockProvider` montem suas respectivas chamadas (`contents=` do genai vs. `messages=[...]` do Converse API) a partir do mesmo texto de instrução — sem duplicar a redação do prompt entre os dois arquivos de provider.

10. **Flag de ambiente `LLM_PROVIDER=gemini|bedrock` em `run_polling/config.py`**, seguindo o padrão já existente de leitura de env vars ali (`os.getenv`, sem validação extra — mesmo estilo de `BOT_TOKEN`/`GEMINI_API_KEY` hoje). Um pequeno factory (`get_llm_provider()`, em `services/llm/__init__.py` ou dentro de `nlp_service.py`/`ocr_service.py`) lê a flag e instancia `GeminiProvider()` ou `BedrockProvider()`. Valor inválido/ausente → default `gemini` (comportamento atual preservado, migração é opt-in).

11. **Validação Pydantic da saída continua obrigatória nos dois providers** — cada provider, depois de obter o JSON (via `response.text` no Gemini, via `response["output"]["message"]["content"][0]["text"]` no Bedrock), faz `json.loads` e constrói `Transacao(**item)` antes de retornar. Nenhum texto de LLM chega ao restante do sistema sem passar por essa validação.

## Arquivos Relevantes

| Arquivo | Papel | Mudança |
|---|---|---|
| `services/llm/provider.py` | **novo** | Interface `LLMProvider` (ABC) |
| `services/llm/gemini_provider.py` | **novo** | Código movido de `nlp_service.py`/`ocr_service.py`, sem mudança de comportamento |
| `services/llm/bedrock_provider.py` | **novo** | Implementação Bedrock (Converse API, Nova Micro/Lite, retry) |
| `services/llm/__init__.py` | **novo** | Factory `get_llm_provider()` lendo `LLM_PROVIDER` |
| `services/nlp_service.py` | modificado | Delega para o provider escolhido; assinatura pública intocada |
| `services/ocr_service.py` | modificado | Lê bytes + mime, delega para o provider; assinatura pública intocada |
| `prompts.py` | modificado | Textos de prompt completos viram constantes, além do `TRANSACTION_SCHEMA` já existente |
| `run_polling/config.py` | modificado | Nova var `LLM_PROVIDER` |
| `handlers/*.py` | **intocados** | Nenhuma mudança — confirma que a abstração não vazou para a camada de apresentação |
| `requirements.txt` | intocado nesta fase | `boto3==1.43.56` já presente (Fase 0); `google-genai` só sai na limpeza pós-estabilidade (fora de escopo) |

## Relação entre os Problemas

Único fio: a ausência de abstração de provedor é a causa raiz que bloqueia tanto "trocar por Bedrock" quanto qualquer troca futura de LLM. As sub-decisões (2, 3, 6, 9, 10) são todas consequências diretas da restrição "handlers não mudam" (CLAUDE.md: zero lógica de negócio em handlers) combinada com "Gemini só é chamado em `ocr_service.py`/`nlp_service.py`" — ambas já eram regras do projeto antes desta fase, não novas.

## Observações de Runtime Confirmadas

- Fase 0 concluída e validada em produção local: `AWS_PROFILE=guardiao-dev python scripts/smoke_test_bedrock.py` → `[Nova Micro / texto] OK -> 'Brasília'`, `[Nova Lite / imagem] OK -> ...` (2026-07-26).
- Região fixada `us-east-2`, mas os IDs de modelo usados são os **inference profiles** (`us.amazon.nova-micro-v1:0`, `us.amazon.nova-lite-v1:0`), não os model IDs puros — já documentado em `docs/PATTERNS.md`, "Decisões Estabelecidas".
- IAM atual (`scripts/aws/iam-policy-guardiao-dev.json`) já cobre `bedrock:InvokeModel` nos ARNs necessários — nenhuma ampliação de IAM necessária nesta fase.

## Perguntas em Aberto

Nenhuma restou sem resposta. Resolvidas nesta sessão via leitura de código + rodada de `AskUserQuestion`:

1. ~~Um TASKS único ou dividir em vários?~~ → Único (ver `Classificação`/escopo abaixo).
2. ~~Onde vive a interface e as implementações?~~ → `services/llm/` (novo subpacote).
3. ~~Retry é interno ao Bedrock ou utilitário compartilhado?~~ → Interno ao `BedrockProvider`.
4. ~~O plano de migração usa `Transacao` singular na assinatura da interface — mantém?~~ → Não; `list[Transacao]`, por CLAUDE.md.
5. ~~Esta decisão (formato da interface `LLMProvider`) estabelece um padrão que fases futuras herdarão?~~ → **Sim.** Nenhuma fase futura troca de LLM de novo, mas o padrão "abstração de provedor + flag de ambiente para rollback" é o mesmo que será usado em `DB_BACKEND=sqlite|dynamo` na Fase 3 (`plano-contexto.md:170`) — vale a pena registrar em `PATTERNS.md` como o padrão de "troca de provedor com flag" a ser seguido lá, mesmo sendo uma rota curta aqui (ver nota em `Classificação`).

## Escopo desta Rodada (confirmado pelo usuário)

Um único TASKS cobre: interface `LLMProvider`, `GeminiProvider` (refactor sem mudança de comportamento), `BedrockProvider` (implementação nova + retry + malformed-output), adaptação de `prompts.py`, flag `LLM_PROVIDER`, validação Pydantic nos dois providers.

**Fora de escopo deste TASKS** (ficam como follow-up manual do usuário, fora do fluxo SDD, pois dependem de dias de observação em produção):
- "Rodar em produção com `bedrock` e monitorar taxa de erro de extração" (`plano-contexto.md:255`) — ação operacional pós-merge, não código.
- "Remover `google-genai` e `GEMINI_API_KEY`" (`plano-contexto.md:256`) — dependente do item anterior confirmar estabilidade; será a Fase 1b/limpeza, uma task futura própria quando o usuário decidir que já rodou tempo suficiente em Bedrock.

## Classificação: Design Conhecido (rota curta)

A causa raiz está fechada (ausência de abstração de provedor), a abordagem é única e sem trade-off remanescente após as decisões 1-11 acima, e todas as perguntas em aberto do INV foram respondidas nesta própria sessão.

**Nota sobre a regra de roteamento:** o critério de `<roteamento>` para rota longa inclui "a decisão estabelece um padrão que tasks futuras seguirão" — e a decisão 5 acima *é* um padrão que a Fase 3 (`DB_BACKEND`) vai seguir. Isso poderia sugerir rota longa. Mas o precedente já aberto neste projeto (`TASKS003-fundacao-aws.md`, rota curta) também gerou múltiplas entradas em `PATTERNS.md` (região AWS, IAM incremental) sem precisar de SPEC/PLN — porque **não havia trade-off real a resolver**, só uma decisão a documentar para reaproveitamento. O discriminador de fato usado neste projeto é "sobra alguma ambiguidade/trade-off depois do INV", não "a decisão será citada de novo". Como não sobrou trade-off aqui, sigo rota curta e registro a decisão 5 tanto na "Decisão de Design" do TASKS quanto em `PATTERNS.md`.

## Próximos Passos

1. Usuário confirma esta classificação (rota curta) e o conteúdo do INV.
2. Escrever `docs/tasks/TASKS004-gemini-para-bedrock.md` com frontmatter `inv: INV002` (sem `spec:`/`plan:` — rota curta).
3. Adicionar entrada em `docs/PATTERNS.md` ("Decisões Estabelecidas") sobre o padrão "abstração de provedor + flag de ambiente para troca reversível", referenciando este INV e o TASKS004.
4. Ao aprovar o TASKS, `/clear` e rodar `/start-task docs/tasks/TASKS004-gemini-para-bedrock.md`.
