---
type: TASKS
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Done
spec:
plan:
inv: INV005
branch: feat/nova-lite-classificacao-texto
---

# TASKS007 — Trocar `nova-micro` por `nova-lite` na classificação de texto

Diagnóstico completo em `docs/analysis/INV005-nova-micro-classificacao-texto.md`. Resumo: `nova-micro` (`TEXT_MODEL_ID`, `services/llm/bedrock_provider.py:14`) classifica "é transação?" de forma não-confiável em pt-BR (variância de amostragem confirmada mesmo com `temperature: 0`); `nova-lite` (já usado hoje em `DOCUMENT_MODEL_ID`) classificou os mesmos 5 inputs corretamente e de forma consistente num A/B real. Custo Bedrock verificado como negligível (`nova-lite` ~1,7x mais caro por token, frações de centavo no volume atual). Pegadinha confirmada: `nova-lite` pode envolver a resposta em cercamento markdown (```` ```json ... ``` ````), diferente do JSON cru de `nova-micro` — o parser precisa ficar tolerante a isso **antes** de trocar o modelo, senão troca uma falha (classificação errada) por outra (`BedrockOutputError` em toda chamada de texto).

**Branch:** esta task roda em `feat/nova-lite-classificacao-texto`, nunca direto na `main` (convenção do `CLAUDE.md`). Criar a branch antes do T1.

## Progresso

- [x] T1
- [x] T2
- [x] T3

## Decisão de Design

Duas mudanças, nesta ordem (a ordem importa — ver pegadinha acima):

1. Tornar `_call_with_malformed_retry` (`services/llm/bedrock_provider.py`) tolerante a cercamento markdown antes de `json.loads`, cobrindo os dois formatos (com e sem cercamento) via TDD.
2. Trocar `TEXT_MODEL_ID` de `us.amazon.nova-micro-v1:0` para `us.amazon.nova-lite-v1:0` — mesmo modelo já usado em `DOCUMENT_MODEL_ID`, decisão fechada em `INV005` (causa raiz e solução únicas, sem trade-off remanescente).

`_call_with_malformed_retry` é compartilhado entre `extract_text_transactions` e `extract_document_transactions` — o fix do parser (T1) protege os dois fluxos automaticamente, mesmo que só o texto esteja trocando de modelo nesta task.

## T1 — Tornar o parser tolerante a cercamento markdown

**Arquivo:** `services/llm/bedrock_provider.py`

**Antes** (linhas 93-102, `_call_with_malformed_retry`):
```python
    async def _call_with_malformed_retry(self, model_id: str, messages: list[dict], parse_fn) -> list[Transacao]:
        for attempt in range(2):
            text = await _converse_with_retry(self._client, model_id, messages)
            try:
                response_data = json.loads(text)
                return parse_fn(response_data)
            except (json.JSONDecodeError, KeyError, ValidationError):
                if attempt == 1:
                    raise BedrockOutputError("Bedrock retornou JSON inválido após re-tentativa")
```

**Depois** (nova função de módulo `_strip_markdown_fence`, usada dentro de `_call_with_malformed_retry`):
```python
def _strip_markdown_fence(text: str) -> str:
    text = text.strip()
    if not text.startswith("```"):
        return text
    text = text.split("\n", 1)[1] if "\n" in text else text[3:]
    if text.endswith("```"):
        text = text[:-3]
    return text.strip()
```
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

**Teste** (`tests/services/llm/test_bedrock_provider.py`, seguir TDD — vermelho antes do código):
- `test_extract_text_transactions_parses_response_wrapped_in_json_markdown_fence`: `_response('```json\n' + json.dumps({"e_transacao": True, "transacoes": [...]}) + '\n```')` → `extract_text_transactions` retorna a transação normalmente (hoje levantaria `BedrockOutputError`, já que `json.loads` falha nas duas tentativas).
- `test_extract_text_transactions_parses_response_wrapped_in_bare_markdown_fence`: mesma coisa, mas cercamento sem a palavra `json` (```` ``` ... ``` ````) — cobre o caso de o modelo não anotar a linguagem.
- Rodar a suíte completa de `test_bedrock_provider.py` existente ao final — nenhum teste já existente deve quebrar (o texto sem cercamento passa por `_strip_markdown_fence` sem alteração, já que não começa com ` ``` `).

**Critério de aceitação:** os dois testes novos passam; os testes já existentes em `test_bedrock_provider.py` continuam passando sem modificação.

## T2 — Trocar `TEXT_MODEL_ID` para `nova-lite`

**Arquivo:** `services/llm/bedrock_provider.py`

**Antes** (linha 14):
```python
TEXT_MODEL_ID = "us.amazon.nova-micro-v1:0"
```

**Depois:**
```python
TEXT_MODEL_ID = "us.amazon.nova-lite-v1:0"
```

Nenhuma mudança de teste necessária: `tests/services/llm/test_bedrock_provider.py` já importa `TEXT_MODEL_ID` do módulo e compara contra ele (`call_kwargs["modelId"] == TEXT_MODEL_ID`), então a asserção acompanha a constante automaticamente.

**Critério de aceitação:** `pytest` continua 100% verde; `grep -n "nova-micro" services/llm/bedrock_provider.py` não retorna mais nenhuma ocorrência.

## T3 — Broadcast em `docs/PATTERNS.md`

Adicionar à seção "Decisões Estabelecidas":

```markdown
### Modelos Nova em `us-east-2` podem cercar a resposta em markdown — parser precisa ser tolerante

Diferentes tiers da família Nova formatam a resposta do Converse API de forma diferente: `nova-micro` responde JSON cru, `nova-lite` pode envolver a resposta em ` ```json ... ``` `. `BedrockProvider._call_with_malformed_retry` (`services/llm/bedrock_provider.py`) agora passa toda resposta por `_strip_markdown_fence` antes de `json.loads`, tolerando os dois formatos (com e sem cercamento, com ou sem a tag `json`). Qualquer troca futura de modelo Nova (ex.: fallback para `nova-pro` em `INV006`/`TASKS008`) deve assumir que o formato de cercamento pode mudar de novo — não assumir JSON cru por padrão. Origem: `docs/analysis/INV005-nova-micro-classificacao-texto.md` / `docs/tasks/TASKS007-nova-lite-classificacao-texto.md`.
```

**Critério de aceitação:** entrada adicionada, sem alterar nenhuma outra seção do arquivo.

## Ordem de Execução

T1 → T2 → T3. T1 antes de T2 é obrigatório (ver pegadinha na Decisão de Design) — trocar o modelo antes do parser tolerante quebraria toda chamada de texto com `BedrockOutputError`.

## Regra do Escoteiro / Testes

- TDD em T1: teste vermelho (com o parser atual) antes de implementar `_strip_markdown_fence`.
- `pytest` na raiz deve passar 100% ao final, incluindo os testes já existentes (nenhum efeito colateral esperado neles, inclusive nos testes de documento que também passam por `_call_with_malformed_retry`).
- Nenhum teste automatizado chama Bedrock real (regra do `CLAUDE.md`) — só client mockado (`Mock()`), igual ao padrão já usado em `test_bedrock_provider.py`.

## Cenários de Teste Manual

1. **Regressão dos casos que falhavam:** enviar via Telegram (com `LLM_PROVIDER=bedrock` real) as mensagens documentadas em `INV005` como falhas do `nova-micro`: `"gastei 10 reais no mercado"`, `"gastei 20 reais no mercado"`, `"comprei pão por 5 reais"`, `"gastei 10 reais na padaria"`, `"gastei 50 reais no cinema"` → todas devem ser reconhecidas como transação.
   - **Executado (via `services.nlp_service.extract_text_transactions` real, chamada direta ao Bedrock/`nova-lite`, mesmo caminho de código do handler, sem passar pelo transporte Telegram):** ✅ as 5 mensagens retornaram transação (`saida`, valores 10/20/5/10/50 corretos).
2. **Não-regressão dos casos que já funcionavam:** `"recebi 100 reais de salario"`, `"paguei 20 reais de uber"` → continuam reconhecidas corretamente.
   - **Executado:** ✅ ambas retornaram transação (`entrada`/100/salario e `saida`/20/transporte).
3. **Mensagem que não é transação:** enviar uma saudação solta (ex.: `"oi, tudo bem?"`) → continua classificada como `e_transacao: false`, sem falso positivo introduzido pela troca de modelo.
   - **Executado:** ✅ retornou lista vazia (sem falso positivo).
4. **Fluxo de documento (regressão indireta):** enviar o PDF de extrato real usado no `TASKS006`/`CONTEXT002` → extração continua funcionando (T1 mexeu no parser compartilhado; confirmar que não introduziu regressão no fluxo de documento, mesmo sem resolver a variância documentada em `INV006`).
   - **Executado (via `provider.extract_document_transactions` real, chamada direta ao Bedrock/`nova-lite`):** ✅ o objetivo deste cenário é só confirmar que o parser compartilhado (T1) não quebrou o fluxo de documento — não validar acurácia de extração de extrato real (isso é escopo do `INV006`/`TASKS008`). Como o PDF original do `TASKS006` foi apagado (nunca commitado), usei um PDF sintético de teste com 2 transações conhecidas. Resultado: as 2 transações vieram corretas (`saida`/30/mercado, `entrada`/500/salário), sem `BedrockOutputError` — confirma que `_strip_markdown_fence` não regrediu o fluxo de documento.

## Fora de Escopo

- Resolver a não-determinismo de extração de **documento** (`INV006`/`TASKS008` — task separada, causa raiz e solução diferentes).
- Qualquer mudança em `repository/dedup.py` ou no contrato de fingerprint.
- Ajustar `build_text_extraction_prompt` (`prompts.py`) — a causa raiz é o modelo, não o prompt (confirmado no INV005 via A/B com o mesmo prompt).

## Validação Final

- [x] `_strip_markdown_fence` implementado e testado (cercado com/sem tag `json`, sem cercamento).
- [x] `TEXT_MODEL_ID` = `us.amazon.nova-lite-v1:0`; nenhuma ocorrência de `nova-micro` restante em `bedrock_provider.py`.
- [x] `docs/PATTERNS.md` com a nova entrada de broadcast.
- [x] `pytest` 100% verde.
- [x] Cenários de Teste Manual 1-4 executados (chamada real ao Bedrock/`nova-lite`, resultados no corpo do TASKS acima).
