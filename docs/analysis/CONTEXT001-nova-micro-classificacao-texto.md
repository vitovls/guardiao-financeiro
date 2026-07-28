---
type: CONTEXT
version: 1.0.0
author: Victor Veloso
date: 2026-07-27
status: Draft
origem: "Descoberto durante teste manual de TASKS006-sqlite-para-dynamodb.md (Cenário 1, fluxo de texto)"
---

# CONTEXT001 — `nova-micro` não classifica com confiança transações em texto (pt-BR)

## Problema

`services/nlp_service.py` → `BedrockProvider.extract_text_transactions` (usa `TEXT_MODEL_ID = "us.amazon.nova-micro-v1:0"`, `services/llm/bedrock_provider.py`) classifica incorretamente mensagens de texto claramente descrevendo uma transação, retornando `e_transacao: false` para casos como `"gastei 10 reais no mercado"`. O usuário recebe "Não foi identificada nenhuma transação nessa mensagem", mesmo com uma frase inequívoca.

**Não é bug do TASKS006** — o texto extraction não foi tocado por essa task (SQLite → DynamoDB). Origem: migração Gemini → Bedrock (`TASKS004-gemini-para-bedrock.md`), que introduziu `nova-micro` como modelo de texto.

## Evidências coletadas (chamadas reais ao Bedrock, fora de teste automatizado)

Prompt usado: exatamente `build_text_extraction_prompt()` de `prompts.py`, sem modificação.

1. **Não-determinismo com temperatura padrão** (`inferenceConfig` sem `temperature` explícito, como hoje em produção): o mesmo input (`"Gastei 10 reais no mercado"`) chamado 4x seguidas retornou `true, false, false, false` — variância pura de amostragem.
2. **`temperature: 0` (decodificação gulosa) não resolve** — fica determinístico por input, mas o resultado "mais provável" segundo o modelo muda com variações mínimas de texto, sem padrão sensato:
   - `"gastei 15 reais no mercado"` → `true`
   - `"gastei 20 reais no mercado"` → `false`
   - `"gastei 25 reais no mercado"` → `true`
   - `"gastei 10 reais no mercado"`, `"gastei 10 reais na padaria"`, `"gastei 50 reais na padaria"`, `"gastei 10 reais no cinema"`, `"gastei 50 reais no cinema"`, `"comprei pão por 5 reais"` → todos `false` (deveriam ser `true`)
   - `"recebi 100 reais de salario"`, `"paguei 20 reais de uber"` → `true` (corretos)
3. **A/B contra `nova-lite`** (`us.amazon.nova-lite-v1:0`, o mesmo modelo já usado em `DOCUMENT_MODEL_ID` para foto/PDF — confirmado funcionando pelo usuário em teste manual real): os mesmos 5 inputs que falhavam em `nova-micro` (incluindo `"gastei 10 reais no mercado"`, `"gastei 20 reais no mercado"`, `"comprei pão por 5 reais"`, `"gastei 10 reais na padaria"`, `"gastei 50 reais no cinema"`) classificaram **corretamente e de forma consistente** com `nova-lite`, mesmo prompt, `temperature: 0`.

## Causa raiz

`nova-micro` não é confiável o suficiente para classificação de "é ou não uma transação financeira" em português a partir de frases curtas — não é um problema de prompt (mesmo prompt funciona bem em `nova-lite`) nem de código em `nlp_service.py`/`bedrock_provider.py`.

## Pegadinha identificada para a correção futura

`nova-lite` envolve a resposta em bloco markdown ```` ```json ... ``` ````, diferente de `nova-micro` (que responde JSON cru). `_call_with_malformed_retry` (`bedrock_provider.py`) hoje faz `json.loads(text)` direto — trocar só o `TEXT_MODEL_ID` sem ajustar o parser troca uma falha (classificação errada) por outra (`BedrockOutputError` em toda chamada de texto). Qualquer correção precisa tornar o parsing tolerante a esse cercamento (`strip` de ```` ```json ```` / ```` ``` ```` antes do `json.loads`), testado com TDD, cobrindo os dois formatos (com e sem cercamento) — não assumir que todo modelo futuro responde igual.

## Recomendação para a próxima task

Trocar `TEXT_MODEL_ID` de `nova-micro` para `nova-lite` em `services/llm/bedrock_provider.py`, alinhado com `DOCUMENT_MODEL_ID` (mesmo modelo pros dois casos de uso), e tornar o parser de `_call_with_malformed_retry` tolerante ao cercamento markdown. Custo adicional de usar `nova-lite` em vez de `nova-micro` para texto não foi medido nesta investigação — vale confirmar se é aceitável antes de aplicar (ver pricing do Bedrock para as duas variantes na região `us-east-2`). Seguir o fluxo SDD normal (`/map-task` → `/start-task`) para essa mudança, não é escopo de `TASKS006`.
