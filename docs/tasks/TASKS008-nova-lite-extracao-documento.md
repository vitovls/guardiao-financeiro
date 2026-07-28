---
type: TASKS
version: 1.2.0
author: Victor Veloso
date: 2026-07-28
status: Done
spec: docs/specs/SPEC008-nova-lite-extracao-documento.md
plan: docs/plans/PLN008-nova-lite-extracao-documento.md
inv: INV006
branch: feat/nova-lite-extracao-documento
---

# TASKS008 — Reduzir não-determinismo da extração de documento (`nova-lite`)

Diagnóstico em `docs/analysis/INV006-nova-lite-extracao-documento-nao-deterministica.md`, requisitos em `docs/specs/SPEC008-nova-lite-extracao-documento.md`, estratégia em `docs/plans/PLN008-nova-lite-extracao-documento.md`. Resumo: reenviar o mesmo PDF de extrato duas vezes deu contagens diferentes de transações (24 vs. 26) e descrições com nível de detalhe variável o bastante para `is_similar()` falhar entre a mesma transação real — quebra o dedup por fingerprint. Mitigação em 3 passos condicionais, **parando no primeiro que resolver**: (1) `temperature=0` explícito, (2) prompt mais restritivo, (3) trocar `DOCUMENT_MODEL_ID` para `nova-pro`. Contrato de dedup (`repository/dedup.py`) não muda em nenhum passo.

**Pré-requisito: `TASKS007-nova-lite-classificacao-texto.md` precisa estar mergeado em `main` antes de começar esta task.** O T1 abaixo assume que `_strip_markdown_fence` (criado em `TASKS007`) já existe em `services/llm/bedrock_provider.py` — o bloco "Antes" de T1 é o estado *pós-TASKS007*, não o estado atual de `main` no momento em que este documento foi escrito. Se `TASKS007` ainda não foi mergeado, implementá-lo primeiro.

**Branch:** esta task roda em `feat/nova-lite-extracao-documento`, criada a partir de `main` **depois** do merge de `feat/nova-lite-classificacao-texto` (TASKS007), nunca direto na `main`. Criar a branch antes do T1.

**Importante para quem implementa:** esta TASKS tem **portões de teste manual** entre os passos (T2, T4, T6). Cada portão usa o mesmo critério fixo (ver "Critério de Aceitação" abaixo) contra o mesmo PDF real usado na investigação do `INV006`. Só avance para o próximo passo de código se o portão anterior **falhar** o critério. Não implemente B ou C especulativamente.

## Progresso

- [x] T1
- [x] T2 (falhou — ver Notas de Execução)
- [x] T3
- [x] T4 (falhou — ver Notas de Execução)
- [x] T3b (v1.1.0)
- [x] T4b (v1.1.0, falhou — ver Notas de Execução)
- [x] T5 (código + IAM policy v5 aplicada e confirmada)
- [x] T6 (passou no critério formal; achado de precisão levou à v1.2.0 — ver Notas de Execução)
- [x] T7 (v1.2.0, código + IAM policy v6 aplicada e confirmada)
- [x] T8 (v1.2.0, passou nos dois critérios — ver Notas de Execução)

## Critério de Aceitação (usado em todos os portões T2/T4/T6)

Extrair o mesmo PDF real de extrato (o mesmo usado no `INV006`) **3 vezes seguidas**, sem nenhuma mudança de arquivo ou input entre as rodadas. Passa se:
(a) a contagem de transações extraídas é idêntica nas 3 rodadas, **e**
(b) para cada transação real que aparece nas 3 rodadas, a descrição extraída em rodadas diferentes passa em `is_similar()` (`repository/dedup.py`, `SIMILARITY_THRESHOLD = 0.8`) comparada par a par (rodada 1 vs. 2, 2 vs. 3, 1 vs. 3).

Falha se (a) ou (b) não se sustentar em qualquer uma das comparações.

## T1 — Parâmetro `temperature` em `_converse_with_retry`

**Arquivo:** `services/llm/bedrock_provider.py`

**Antes** (linhas 30-47):
```python
async def _converse_with_retry(client, model_id: str, messages: list[dict]) -> str:
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig={"maxTokens": _MAX_OUTPUT_TOKENS},
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
```

**Depois:**
```python
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
```

**Arquivo:** `services/llm/bedrock_provider.py` — `extract_document_transactions` e `_call_with_malformed_retry` precisam repassar `temperature` até `_converse_with_retry`.

**Antes** (linhas 68-72):
```python
    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        label = "PDF" if mime_type in _MIME_TO_DOCUMENT_FORMAT else "imagem"
        prompt = build_document_extraction_prompt(label)
        content_block = self._build_content_block(file_bytes, mime_type)
        messages = [{"role": "user", "content": [content_block, {"text": prompt}]}]
        return await self._call_with_malformed_retry(DOCUMENT_MODEL_ID, messages, self._parse_document_response)
```

**Depois:**
```python
    async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
        label = "PDF" if mime_type in _MIME_TO_DOCUMENT_FORMAT else "imagem"
        prompt = build_document_extraction_prompt(label)
        content_block = self._build_content_block(file_bytes, mime_type)
        messages = [{"role": "user", "content": [content_block, {"text": prompt}]}]
        return await self._call_with_malformed_retry(
            DOCUMENT_MODEL_ID, messages, self._parse_document_response, temperature=0.0
        )
```

**Antes** (linhas 93-102, `_call_with_malformed_retry` — já assume que `TASKS007` implementou `_strip_markdown_fence`):
```python
    async def _call_with_malformed_retry(self, model_id: str, messages: list[dict], parse_fn) -> list[Transacao]:
        for attempt in range(2):
            text = await _converse_with_retry(self._client, model_id, messages)
            try:
                response_data = json.loads(_strip_markdown_fence(text))
                return parse_fn(response_data)
            except (json.JSONDecodeError, KeyError, ValidationError):
                if attempt == 1:
                    raise BedrockOutputError("Bedrock retornou JSON inválido após re-tentativa")
```

**Depois:**
```python
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
```

`extract_text_transactions` não muda — continua chamando `_call_with_malformed_retry` sem o argumento `temperature`, que fica `None` por default (nenhuma mudança de comportamento no fluxo de texto, requisito A2/D2 do `SPEC008`).

**Teste** (`tests/services/llm/test_bedrock_provider.py`, TDD):
- `test_extract_document_transactions_passes_temperature_zero`: mockar `client.converse`, chamar `extract_document_transactions`, verificar `call_kwargs["inferenceConfig"]["temperature"] == 0.0`.
- `test_extract_text_transactions_does_not_set_temperature`: mesma verificação para `extract_text_transactions` — `"temperature" not in call_kwargs["inferenceConfig"]` (regressão para garantir que o fluxo de texto não foi afetado).
- Rodar a suíte completa existente — nenhum teste já existente deve quebrar (todos chamam `_call_with_malformed_retry`/`_converse_with_retry` sem o novo argumento, que tem default `None`).

**Critério de aceitação:** os dois testes novos passam; suíte completa de `test_bedrock_provider.py` continua verde.

## T2 — Portão de teste manual #1 (temperature=0)

Com `LLM_PROVIDER=bedrock` real, enviar o mesmo PDF de extrato do `INV006` 3 vezes seguidas via Telegram (ou script equivalente que chame `extract_document_transactions` diretamente, sem passar pelo bot, se mais prático). Avaliar contra o "Critério de Aceitação" no topo deste documento.

- **Se passar:** parar aqui. T3-T6 não são implementados. Ir direto para "Validação Final", marcando os itens de T1 e este portão.
- **Se falhar:** documentar o resultado (contagens das 3 rodadas, quais pares de descrição falharam em `is_similar()`) e seguir para T3.

## T3 — Prompt mais restritivo (só se T2 falhou)

**Arquivo:** `prompts.py`

**Antes** (linhas 14-18):
```python
def build_document_extraction_prompt(document_label: str) -> str:
    return (
        f"Extraia as transações deste(a) {document_label} de extrato bancário. "
        f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"
    )
```

**Depois:**
```python
def build_document_extraction_prompt(document_label: str) -> str:
    return (
        f"Extraia as transações deste(a) {document_label} de extrato bancário. "
        "Para cada transação, inclua na descrição o nome completo do remetente ou "
        "beneficiário e os detalhes de conta/agência exatamente como aparecem no "
        "documento — nunca resuma ou omita essas informações, mesmo que se repitam "
        "entre transações. "
        f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"
    )
```

`build_text_extraction_prompt` não é tocado.

**Teste:** se `tests/test_prompts.py` (ou equivalente) tiver uma asserção de string exata do prompt de documento, atualizar para o novo texto. Não é necessário TDD aqui (é uma mudança de conteúdo de string, não de lógica) — só manter o teste existente verde.

**Critério de aceitação:** `pytest` continua 100% verde.

## T4 — Portão de teste manual #2 (temperature=0 + prompt restritivo)

Repetir exatamente o mesmo procedimento do T2 (mesmo PDF, 3 rodadas, mesmo critério).

- **Se passar:** parar aqui. T5-T6 não são implementados. Ir para "Validação Final".
- **Se falhar:** documentar o resultado e seguir para T5.

**Adendo v1.1.0 (T4 falhou, ver Notas de Execução):** antes de escalar para `nova-pro` (T5), o usuário pediu mais uma iteração de prompt (T3b) para uma causa de falha específica e nova encontrada em T4 — subtotal/saldo do extrato sendo tratado como transação, não descrição verbosa nem truncamento (confirmado via diagnóstico de `stopReason`/`usage`, `stopReason: end_turn` nas 3 rodadas, bem abaixo do limite de `maxTokens`). T3b/T4b rodam antes de T5.

## T3b — Terceira iteração de prompt (excluir subtotal/saldo tratados como transação)

**Motivação:** T4 (T3 + temperature=0) falhou com contagens 24/54/24. A causa raiz da Rodada 2 (54 itens) não foi truncamento (`stopReason: end_turn` nas 3 rodadas, `outputTokens` 2715-3895, bem abaixo de `_MAX_OUTPUT_TOKENS = 5000`) — o modelo alucinou linhas de "Total de saídas" (subtotal por dia) do extrato como se fossem transações individuais, intercaladas com transações reais.

**Arquivo:** `prompts.py`

**Antes** (estado pós-T3):
```python
def build_document_extraction_prompt(document_label: str) -> str:
    return (
        f"Extraia as transações deste(a) {document_label} de extrato bancário. "
        "Para cada transação, inclua na descrição o nome completo do remetente ou "
        "beneficiário e os detalhes de conta/agência exatamente como aparecem no "
        "documento — nunca resuma ou omita essas informações, mesmo que se repitam "
        "entre transações. "
        f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"
    )
```

**Depois:**
```python
def build_document_extraction_prompt(document_label: str) -> str:
    return (
        f"Extraia as transações deste(a) {document_label} de extrato bancário. "
        "Uma transação é uma movimentação individual e específica de dinheiro — um Pix, "
        "uma compra no débito, uma transferência — sempre associada a um remetente, "
        "beneficiário ou estabelecimento nomeado. "
        'NÃO são transações, mesmo que tenham valor em R$: linhas de "Total de entradas" '
        'ou "Total de saídas" (são subtotais, não movimentações individuais), '
        '"Saldo inicial", "Saldo final", "Saldo do período" ou "Saldo do dia", qualquer '
        "coluna de saldo corrente/acumulado, e cabeçalhos de tabela/página ou rodapé com "
        "CNPJ/atendimento/SAC — ignore essas linhas completamente. "
        "Para cada transação, inclua na descrição o nome completo do remetente ou "
        "beneficiário e os detalhes de conta/agência exatamente como aparecem no "
        "documento — nunca resuma ou omita essas informações, mesmo que se repitam "
        "entre transações. "
        f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"
    )
```

`TRANSACTION_SCHEMA` não muda (permanece sem campo `status`, sem instrução de sinal em `valor` — decisão explícita para não vazar mudança de schema para `build_text_extraction_prompt`, que continua intocado). `build_text_extraction_prompt` não é tocado.

**Teste:** mesmo caso de T3 — mudança de conteúdo de string, sem lógica nova. Manter `tests/test_prompts.py` verde.

**Critério de aceitação:** `pytest` continua 100% verde.

## T4b — Portão de teste manual #3b (temperature=0 + prompt com exclusão de subtotal/saldo)

Repetir exatamente o mesmo procedimento do T2/T4 (mesmo PDF, 3 rodadas, mesmo critério).

- **Se passar:** parar aqui. T5-T6 não são implementados. Ir para "Validação Final".
- **Se falhar:** documentar o resultado e seguir para T5 (mitigação de 3 passos original esgotada; T3b foi uma iteração extra dentro do passo 2, não um 4º passo novo).

## T5 — Trocar `DOCUMENT_MODEL_ID` para `nova-pro` (só se T4 falhou)

**Antes de codificar:** confirmar na documentação oficial da AWS (`docs.aws.amazon.com/bedrock`) o model ID exato do inference profile de `nova-pro` em `us-east-2` e o preço atual por token — a tabela do `PLN008` usa valores de pesquisa web não confirmados oficialmente no momento da escrita.

**Arquivo:** `services/llm/bedrock_provider.py` (linha 15):

**Antes:**
```python
DOCUMENT_MODEL_ID = "us.amazon.nova-lite-v1:0"
```

**Depois:**
```python
DOCUMENT_MODEL_ID = "us.amazon.nova-pro-v1:0"
```

**Arquivo:** `scripts/aws/iam-policy-guardiao-dev.json` — ampliar os dois `Statement`s de Bedrock já existentes com as entradas de `nova-pro` (mesmo padrão de `nova-micro`/`nova-lite`, não criar `Sid` novo):

**Depois** (`BedrockInvokeGeoInferenceProfileGuardiaoDev.Resource`, acrescentar):
```json
"arn:aws:bedrock:us-east-2:413948096391:inference-profile/us.amazon.nova-pro-v1:0"
```

**Depois** (`BedrockInvokeFoundationModelGuardiaoDev.Resource`, acrescentar as 3 regiões):
```json
"arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-pro-v1:0",
"arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-pro-v1:0",
"arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-pro-v1:0"
```

Comando para o usuário rodar após o commit (nova *policy version*, mesmo padrão de `TASKS003` — modificar uma IAM policy é ação de conta/admin, então **sem** `--profile guardiao-dev`, usando o profile default do AWS CLI):
```bash
aws iam create-policy-version \
  --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock \
  --policy-document file://scripts/aws/iam-policy-guardiao-dev.json \
  --set-as-default
```

**Critério de aceitação:** `aws iam get-policy-version --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock --version-id <nova-versao> --profile guardiao-dev` mostra as 4 novas entradas de `nova-pro`.

**Teste:** atualizar `tests/services/llm/test_bedrock_provider.py` onde `DOCUMENT_MODEL_ID` é usado em asserções (já importa a constante do módulo, deve acompanhar automaticamente).

**Broadcast em `docs/PATTERNS.md`** (seção "Decisões Estabelecidas"):
```markdown
### Fallback de modelo por robustez segue a mesma família Nova antes de trocar de provedor

Quando um modelo Nova (`nova-micro`/`nova-lite`) não é confiável o bastante para uma tarefa (classificação de texto, extração de documento), o primeiro fallback é o próximo tier da mesma família (`nova-pro`), não um provedor diferente — reaproveita o mesmo padrão de inference profile/IAM já estabelecido (`INV001`), só ampliando os `Statement`s existentes com o novo model ID, sem `Sid` novo. Trocar de provedor (ex. Claude via Bedrock) só se o próximo tier Nova também falhar — decisão registrada, não eliminada, mas não tentada nesta fase. Origem: `docs/analysis/INV006-nova-lite-extracao-documento-nao-deterministica.md` / `docs/tasks/TASKS008-nova-lite-extracao-documento.md`.
```

**Critério de aceitação:** entrada adicionada, sem alterar nenhuma outra seção do arquivo.

## T6 — Portão de teste manual #3 (validação final, só se T5 foi implementado)

Repetir o mesmo procedimento do T2/T4 (mesmo PDF, 3 rodadas, mesmo critério), agora com `nova-pro`.

- **Se passar:** ir para "Validação Final".
- **Se falhar:** a mitigação de 3 passos deste TASKS se esgotou — não inventar um 4º passo aqui. Documentar o resultado em uma atualização de `INV006` (nova seção "Resultado das mitigações testadas") e voltar para `/map-task` para reabrir a decisão (ex. comparar Claude Haiku, ou reconsiderar o contrato de fingerprint) — fora do escopo desta TASKS.

**Adendo v1.2.0 (T6 passou no critério formal, mas achado de precisão — ver Notas de Execução):** o determinismo (objetivo original desta TASKS) está resolvido a partir de `nova-pro`. Só que a extração ainda perde 3 transações reais de forma sistemática (mesmas 3 em toda rodada) — um problema de precisão/segmentação de layout, eixo diferente do que esta TASKS foi desenhada para resolver. O usuário decidiu tratar isso reabrindo o escopo desta mesma TASKS (em vez de um `/map-task` novo), testando `meta.llama4-maverick-17b-instruct-v1:0` (Llama 4 Maverick, fora da família Nova) como próximo candidato. Isso contradiz a ordem original ("trocar de provedor só se o próximo tier Nova também falhar") porque `nova-pro` não falhou no eixo de determinismo — a troca de provedor está acontecendo por um eixo (precisão) que a decisão original nunca cobriu. Ver T7/T8.

## T7 — Trocar `DOCUMENT_MODEL_ID` para Llama 4 Maverick (v1.2.0)

**Confirmado antes de codificar** (`docs.aws.amazon.com/bedrock/latest/userguide/model-card-meta-llama-4-maverick-17b-instruct.html`): model ID `meta.llama4-maverick-17b-instruct-v1:0`, Geo Inference ID `us.meta.llama4-maverick-17b-instruct-v1:0`, com `us-east-2` como origem/destino Geo válido — mesmo padrão de inference profile do Nova. Converse API suportada. Max output tokens: 8K (nosso `_MAX_OUTPUT_TOKENS = 5000` continua válido, folga maior que com Nova).

**Smoke test manual (fora do repo, não commitado)** contra o mesmo PDF real, usando bloco de conteúdo `{"document": {"format": "pdf", ...}}` (mesmo formato que já usamos para Nova) — a dúvida era se o modelo aceita esse tipo de bloco, já que o model card só lista Image/Text como modalidade de entrada suportada, sem "Document" explícito:
- **Resultado: funciona.** `stopReason: end_turn`, resposta JSON válida, sem cerca de markdown (diferente do Nova, que às vezes cerca com ` ```json `) — `_strip_markdown_fence` continua seguro (é um no-op quando não há cerca).
- Tokens de entrada para o mesmo PDF: ~3.147 (Llama) vs. ~10.570-10.723 (Nova) — tokenizer bem mais eficiente para este documento.

**Preço on-demand (pesquisa web, não documentação oficial de pricing):** Llama 4 Maverick ~US$0,24/1M tokens de entrada, ~US$0,97/1M de saída — mais barato que `nova-pro` (~US$0,80/~US$3,20), mais caro que `nova-lite` (~US$0,06/~US$0,24). Combinado com o menor consumo de tokens de entrada, o custo por chamada real tende a ficar ainda mais baixo que a razão de preço por token sozinha sugere.

**Arquivo:** `services/llm/bedrock_provider.py` (mesma constante do T5, sem novo flag/abstração — é troca de valor de `DOCUMENT_MODEL_ID`, mesmo padrão do T5, não uma segunda implementação de provider):

**Antes:**
```python
DOCUMENT_MODEL_ID = "us.amazon.nova-pro-v1:0"
```

**Depois:**
```python
DOCUMENT_MODEL_ID = "us.meta.llama4-maverick-17b-instruct-v1:0"
```

**Arquivo:** `scripts/aws/iam-policy-guardiao-dev.json` — mesmo padrão do T5, ampliar os 2 `Statement`s existentes (sem `Sid` novo):

**Depois** (`BedrockInvokeGeoInferenceProfileGuardiaoDev.Resource`, acrescentar):
```json
"arn:aws:bedrock:us-east-2:413948096391:inference-profile/us.meta.llama4-maverick-17b-instruct-v1:0"
```

**Depois** (`BedrockInvokeFoundationModelGuardiaoDev.Resource`, acrescentar as 3 regiões):
```json
"arn:aws:bedrock:us-east-1::foundation-model/meta.llama4-maverick-17b-instruct-v1:0",
"arn:aws:bedrock:us-east-2::foundation-model/meta.llama4-maverick-17b-instruct-v1:0",
"arn:aws:bedrock:us-west-2::foundation-model/meta.llama4-maverick-17b-instruct-v1:0"
```

Comando para o usuário rodar após o commit (mesmo padrão do T5 — profile default, sem `--profile guardiao-dev`):
```bash
aws iam create-policy-version \
  --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock \
  --policy-document file://scripts/aws/iam-policy-guardiao-dev.json \
  --set-as-default
```

**Critério de aceitação:** `aws iam get-policy-version ... --profile guardiao-dev` mostra as 4 novas entradas de Llama 4 Maverick; `tests/services/llm/test_bedrock_provider.py` acompanha automaticamente (importa `DOCUMENT_MODEL_ID` do módulo); `pytest` 100% verde.

**Atualizar broadcast em `docs/PATTERNS.md`** (a entrada "Fallback de modelo por robustez segue a mesma família Nova antes de trocar de provedor", criada no T5, precisa de um adendo — o próprio T6 passou no eixo que motivou aquela regra, e a troca de provedor aconteceu por um eixo diferente, precisão, não determinismo).

## T8 — Portão de teste manual #4 (Llama 4 Maverick) — critério duplo

Mesmo procedimento de 3 rodadas do mesmo PDF, mas com **dois critérios avaliados separadamente**, porque o critério original (T2/T4/T6) só testa determinismo e já provou passar mesmo com 3 transações reais faltando (T6):

**Critério de determinismo (igual ao topo do documento):** (a) contagem idêntica nas 3 rodadas, (b) `is_similar()` par a par ≥ 0.8 para toda transação presente em mais de uma rodada.

**Critério de precisão (novo nesta v1.2.0), contra as 44 transações reais confirmadas do PDF (ver Notas de Execução do T6):**
- As 3 transações antes ausentes com `nova-pro` aparecem agora? (05/06 Mercadinho Bombonier R$9,30; 09/06 IFD*Ifood Club R$7,95; 10/06 Hora Dum Pao R$3,00)
- `R$ 3.699,60` (BPI Data Tecnologia, 05/06) continua correto (não `R$ 3.70`, não JSON malformado)?
- Contagem total bate com 44 (ou está mais perto disso que as 41 do `nova-pro`)?

- **Se os dois critérios passarem:** ir para "Validação Final".
- **Se o critério de determinismo falhar:** documentar e decidir com o usuário se vale tentar `temperature=0` (Llama pode ter comportamento de sampling diferente do Nova) antes de descartar o modelo — não inventar isso sem aprovação, é uma iteração nova.
- **Se o critério de precisão falhar (determinismo passa, mas continua perdendo transações):** documentar como achado — pode ser limitação inerente de segmentação de PDF de qualquer modelo Bedrock testado até aqui, não corrigível só trocando modelo. Registrar em `INV006` e decidir com o usuário se vale investigar mais (ex. pré-processar o PDF em imagens por página) como nova iteração, fora desta TASKS.

## Ordem de Execução

T1 → T2 (portão) → [T3 → T4 (portão)] → [T3b → T4b (portão)] → [T5 → T6 (portão)] → [T7 → T8 (portão)]. Os blocos entre colchetes só rodam se o portão anterior falhar (T7/T8 são exceção: rodam mesmo com T6 tendo passado no critério formal, por decisão do usuário de tratar o achado de precisão dentro desta TASKS). Cada T de código (T1, T3, T3b, T5, T7) é seguido imediatamente pelo portão de teste manual correspondente antes de decidir se o próximo T é necessário. T3b/T4b foram adicionados na v1.1.0 como uma iteração extra dentro do passo 2 (prompt). T7/T8 foram adicionados na v1.2.0 para tratar um achado de precisão (não de determinismo) que sobreviveu ao T6.

## Regra do Escoteiro / Testes

- TDD em T1 (vermelho antes do parâmetro `temperature`), seguindo `superpowers:test-driven-development`.
- `pytest` deve passar 100% ao final de cada T de código, antes de avançar para o próximo portão.
- Nenhum teste automatizado chama Bedrock real — os portões (T2/T4/T6) são os únicos pontos de chamada real, sempre manuais, nunca automatizados (regra do `CLAUDE.md`).
- Se T5 for alcançado, criação/edição da IAM policy segue `PATTERNS.md` ("criação de recursos AWS é sempre ação manual do usuário" — o Claude Code edita o JSON, o usuário roda o comando CLI).

## Cenários de Teste Manual

Já cobertos pelos portões T2/T4/T4b/T6/T8 (são os únicos cenários manuais desta task — não há cenário adicional além deles). Resultado final: T8 passou nos dois critérios (determinismo + precisão) — ver "Notas de Execução".

## Fora de Escopo

- Qualquer mudança no fluxo de texto (`nova-micro`/`nova-lite`, `TASKS007`) — task independente.
- Mudar o contrato de fingerprint/dedup (`repository/dedup.py`, `SPEC006`).
- Automatizar o teste de variância (rodar N extrações programaticamente e comparar) — os portões são manuais por decisão já registrada no `SPEC008`.
- ~~Comparar Claude Haiku (ou qualquer modelo fora da família Nova) — só se T6 falhar, e mesmo assim como nova iteração de `/map-task`, não dentro desta TASKS.~~ **Superado na v1.2.0:** o usuário decidiu tratar a troca de provedor (Llama 4 Maverick) dentro desta própria TASKS, para o eixo de precisão (T6 passou no eixo de determinismo que esta restrição original previa) — ver T7/T8. Continua fora de escopo comparar **outros** modelos além do já decidido (Llama 4 Maverick) sem nova aprovação.
- Pré-processar o PDF em imagens por página (ex. para contornar limitação de segmentação de layout) — só cogitar como nova iteração se T8 falhar no critério de precisão, não implementar especulativamente.
- Popular `.env`/documentação de custo de produção — fora do pedido desta task.

## Notas de Execução

### T2 — Resultado (FALHOU)

Executado com `scripts/manual_test_document_extraction_variance.py` (script criado para este portão, chama `BedrockProvider.extract_document_transactions` diretamente, sem passar pelo bot) contra o PDF real do `INV006` (`files/1785197109-NU_47358680_01JUN2026_26JUN2026.pdf`), 3 rodadas seguidas, já com `temperature=0.0` (T1).

**Critério (a) — contagem idêntica: FALHOU.** Rodada 1 = 26, Rodada 2 = 27, Rodada 3 = 29.

**Critério (b) — `is_similar()` par a par: PASSOU onde testável.** As 3 rodadas são estritamente aninhadas — R2 = R1 + 1 transação nova, R3 = R2 + 2 transações novas — sem nenhuma omissão de transação já presente numa rodada anterior. Toda transação com a mesma `(data, valor, tipo)` presente em mais de uma rodada tem descrição **idêntica** entre as rodadas (`is_similar()` = 1.0, bem acima do `SIMILARITY_THRESHOLD = 0.8`).

**Leitura:** diferente do cenário original do `INV006` (onde a descrição variava de detalhe para a mesma transação e derrubava `is_similar()`), aqui `temperature=0` parece ter estabilizado o *conteúdo* da descrição — o problema que falhou o portão foi puramente de **contagem/inclusão de transação**, não de verbosidade. `nova-lite` está omitindo transações reais de forma inconsistente entre chamadas idênticas, nunca inventando ou revertendo uma já extraída.

**Sinal adicional (não é critério formal do portão, não usar como número confirmado):** uma releitura independente do mesmo PDF (fora do `BedrockProvider`, feita à parte) reportou 44 transações no extrato — bem acima das 26-29 extraídas pelo `nova-lite` nas 3 rodadas. Sugere que a subcontagem pode ser maior do que a variância rodada-a-rodada isoladamente mostra, mas não é uma contagem verificada para registro permanente.

**Ressalva para T3/T4:** o prompt mais restritivo de T3 instrui a nunca resumir/omitir *detalhes da descrição* (nome do remetente, conta/agência) — não instrui explicitamente contra omitir *transações inteiras*. É o próximo passo prescrito pelo TASKS mesmo assim (mitigação de 3 passos já decidida, barata de testar), mas pode não atacar o eixo que efetivamente falhou este portão. Se T4 falhar pelo mesmo motivo (contagem, não descrição), isso é esperado e não invalida a ordem de mitigação — seguir para T5.

### T4 — Resultado (FALHOU)

Mesmo procedimento do T2, agora com o prompt mais restritivo do T3 + `temperature=0.0`. Contra o mesmo PDF real:

**Critério (a) — contagem idêntica: FALHOU.** Rodada 1 = 24, Rodada 2 = 54, Rodada 3 = 24.

**Diagnóstico de causa (script ad-hoc, fora do repo, chamando `client.converse` diretamente para capturar `stopReason`/`usage` — não commitado, só para esta investigação):** nas 3 rodadas `stopReason: end_turn` (resposta completa, não cortada) e `outputTokens` entre 2715 e 3895 — bem abaixo de `_MAX_OUTPUT_TOKENS = 5000`. **Não é truncamento.** A Rodada 2 (54 itens) incluiu diversas linhas de `"Total de saídas"` (subtotal por dia do extrato) formatadas como se fossem transações individuais, intercaladas com as transações reais — alucinação de conteúdo estrutural (subtotal vs. movimentação), não corte de output nem variação de detalhe de descrição.

**Decisão do usuário:** tentar mais uma iteração de prompt (T3b/T4b, adicionada nesta v1.1.0) antes de escalar para `nova-pro` (T5) — instruir explicitamente contra tratar subtotal/saldo/cabeçalho como transação. Ver T3b para o diff aplicado.

### T4b — Resultado (FALHOU)

Portão oficial (`scripts/manual_test_document_extraction_variance.py`, 3 rodadas, mesmo PDF), com o prompt T3b (`temperature=0.0` + exclusão explícita de subtotal/saldo).

**Critério (a) — contagem idêntica: FALHOU, e piorou.** Rodada 1 = 38, Rodada 2 = 55, Rodada 3 = 54 — variância maior que a de T4 (24/54/24).

**A própria mitigação de T3b não funcionou:** linhas de `"Total de saídas"` continuam aparecendo como transações nas Rodadas 2 e 3 (11 ocorrências em cada, agora com valor negativo, ex. `2026-06-09 | saida | R$ -237.95 | 'Total de saídas'`), apesar da instrução explícita para ignorá-las.

**Achado novo, fora do escopo desta TASKS (não corrigido aqui):** identificado um bug de parsing de valor em formato brasileiro (milhar com ponto, decimal com vírgula) — uma transação real de `R$ 3.699,60` (BPI Data Tecnologia Ltda, recebimento PJ em 05/06, confirmada por releitura independente do mesmo PDF) é consistentemente lida como `R$ 3.70` em todas as extrações testadas (T2/T4/T4b), e numa amostra diagnóstica ad-hoc (6 rodadas, fora do portão oficial, não commitada) o mesmo valor gerou JSON inválido (`"valor": 3.699.6`, dois pontos decimais) em 1 de 6 tentativas. Esse bug é de **precisão de valor**, não de determinismo de contagem/descrição — não está coberto por nenhum critério de aceitação desta TASKS (`Fora de Escopo` nunca menciona precisão numérica) e não bloqueia a decisão de T4b (contagem já falhou por variância, independente deste bug). Registrar como possível follow-up de `INV006` ou nova investigação futura — não corrigir dentro de `TASKS008`.

**Decisão:** duas iterações de prompt (T3, T3b) tentadas, ambas com variância pior que a anterior — convergência falhou. Sem inventar uma 4ª iteração de prompt; seguir para T5 (`nova-pro`) conforme a mitigação de 3 passos já decidida.

### T5 — Confirmação oficial (antes de codificar)

Confirmado em `docs.aws.amazon.com/bedrock/latest/userguide/model-card-amazon-nova-pro.html`: model ID `amazon.nova-pro-v1:0`, Geo Inference ID `us.amazon.nova-pro-v1:0`, com `us-east-2` listado como origem/destino válido do Geo cross-region — igual ao que já estava escrito no TASKS, sem necessidade de correção. Preço on-demand (AWS Bedrock Pricing, pesquisa web): Nova Pro ~US$0,80/1M tokens de entrada e ~US$3,20/1M de saída, vs. Nova Lite ~US$0,06/1M entrada e ~US$0,24/1M saída — razão ~13,3x, confere com a estimativa não confirmada do `PLN008`.

### T6 — Resultado (PASSOU no critério formal, mas achado de precisão motivou v1.2.0)

Portão oficial, 3 rodadas, mesmo PDF, agora com `nova-pro`.

**Critério (a) — contagem idêntica: PASSOU.** Rodada 1 = 41, Rodada 2 = 41, Rodada 3 = 41.

**Critério (b) — `is_similar()` par a par: PASSOU.** As 41 transações são as mesmas nas 3 rodadas, na mesma ordem, com descrições variando só em erros de OCR de caractere isolado (ex. "BOC DO BRASIL" vs "BCDO DO BRASIL", "VELOS0" vs "VELSO") — similaridade bem acima de 0,8 em todos os pares checados. Também resolveu o bug de moeda do T4b: `R$ 3.699,60` (BPI Data Tecnologia) agora é lido corretamente nas 3 rodadas (era `R$ 3.70` com `nova-lite`). Nenhuma linha de `"Total de saídas"` tratada como transação (problema do T4/T4b não recorreu).

**Achado novo (fora do critério formal, motivou reabertura de escopo):** cruzando contra o texto real do PDF (lido via ferramenta, 6 páginas, 44 transações reais confirmadas), **3 transações reais estão sistematicamente ausentes nas 3 rodadas** (mesmas 3, sempre):
- 05/06 — Compra no débito MERCADINHO BOMBONIER — R$ 9,30 (saída)
- 09/06 — Compra no débito IFD*IFOOD CLUB — R$ 7,95 (saída)
- 10/06 — Compra no débito HORA DUM PAO — R$ 3,00 (saída)

Padrão 100% consistente no documento inteiro: as 3 ausentes são exatamente os casos em que um dia tem bloco "Total de entradas" **e** "Total de saídas", e o primeiro item do bloco de saídas é um "Compra no débito" de uma linha, imediatamente seguido por um "Transferência enviada pelo Pix" com descrição longa (várias linhas). Nenhum outro dia do extrato com essa combinação existe, e em nenhum outro caso onde "Compra no débito" aparece em outra posição do bloco ele é descartado — confirmado conferindo os 7 outros dias com ambos os blocos. Como é uma omissão de **precisão/segmentação de layout**, não de **determinismo** (é idêntica nas 3 rodadas), o critério formal do portão passa mesmo assim.

**Decisão do usuário:** tratar a precisão é importante o bastante para reabrir o escopo desta TASKS (v1.2.0) em vez de abrir um `/map-task` novo — trocar `DOCUMENT_MODEL_ID` para `meta.llama4-maverick-17b-instruct-v1:0` (fora da família Nova). Ver T7/T8 abaixo.

### T8 — Resultado (PASSOU nos dois critérios)

Portão oficial, 3 rodadas, mesmo PDF, com `meta.llama4-maverick-17b-instruct-v1:0`.

**Critério de determinismo:**
- (a) contagem idêntica: **PASSOU** — 44/44/44.
- (b) `is_similar()` par a par: **PASSOU** — descrições **byte-a-byte idênticas** nas 3 rodadas para todas as 44 transações (não só acima do threshold — idênticas), incluindo os casos que antes tinham erro de OCR de caractere isolado com `nova-pro`.

**Critério de precisão:**
- As 3 transações antes ausentes com `nova-pro` **aparecem nas 3 rodadas**: 05/06 Mercadinho Bombonier R$9,30; 09/06 IFD*Ifood Club R$7,95; 10/06 Hora Dum Pao R$3,00.
- `R$ 3.699,60` (BPI Data Tecnologia) correto nas 3 rodadas (não `R$ 3.70`, não malformado).
- Contagem total = 44, **exatamente igual** ao número de transações reais confirmadas no PDF (nenhuma sobra, nenhuma falta).
- Conferência adicional: soma das 9 transações de entrada = R$ 4.963,60, bate exatamente com "Total de entradas" declarado no cabeçalho do extrato.
- Achado bônus (não pedido, mas observado): duas descrições que ficavam truncadas em quebra de página com `nova-pro`/`nova-lite` (Pix de R$3.725,30 cortado em "...BANCO"; Pix do Wilson de Santana Silva cortado antes do "PICPAY (0380) Agência...") agora vêm completas nas 3 rodadas.

**Conclusão:** `meta.llama4-maverick-17b-instruct-v1:0` resolve tanto o eixo de determinismo (objetivo original da TASKS) quanto o eixo de precisão (achado do T6, motivo da reabertura de escopo v1.2.0), sem regressão em nenhum dos dois. Nenhuma iteração adicional necessária.

## Validação Final

- [x] T1: parâmetro `temperature` implementado e testado; fluxo de texto sem mudança de comportamento (teste de regressão específico).
- [x] Portão de aceitação: T2 falhou (26/27/29), T4 falhou (24/54/24, mais achado de subtotal-como-transação), T4b falhou (38/55/54, mesmo achado persistindo), T6 passou no determinismo (41/41/41) mas revelou achado de precisão (3 transações sistematicamente ausentes), T8 passou nos dois critérios (44/44/44, descrições idênticas, contagem = ground truth). Todas as contagens e resultados de `is_similar()` documentados em "Notas de Execução".
- [x] T3 implementado: `build_document_extraction_prompt` atualizado (T3, depois T3b); `build_text_extraction_prompt` intocado em todo o processo.
- [x] T5 implementado: `DOCUMENT_MODEL_ID` passou por `us.amazon.nova-pro-v1:0` (model ID confirmado contra doc oficial da AWS) — IAM policy v5 ampliada e aplicada; `docs/PATTERNS.md` com a entrada de broadcast.
- [x] T7 implementado (v1.2.0, achado de precisão pós-T6): `DOCUMENT_MODEL_ID` final = `us.meta.llama4-maverick-17b-instruct-v1:0` (model ID confirmado contra doc oficial da AWS, Converse API + bloco `document` testados via smoke test manual antes de codificar); IAM policy v6 ampliada e aplicada; `docs/PATTERNS.md` com o adendo sobre eixos independentes (determinismo vs. precisão).
- [x] `pytest` 100% verde no ponto de parada final (105 testes, ver evidência abaixo).
- [x] Nenhuma mudança em `repository/dedup.py` ou no fluxo de texto em nenhum ponto de parada (confirmado: `TEXT_MODEL_ID`, `extract_text_transactions` e `build_text_extraction_prompt` nunca tocados; `git status` mostra só `prompts.py`, `services/llm/bedrock_provider.py`, `tests/services/llm/test_bedrock_provider.py`, `scripts/aws/iam-policy-guardiao-dev.json`, `docs/PATTERNS.md` modificados, mais `scripts/manual_test_document_extraction_variance.py` novo).

**Evidência da verificação final** (`superpowers:verification-before-completion`, comando rodado nesta sessão):
```
$ pytest
============================= 105 passed in 1.53s ==============================
```
