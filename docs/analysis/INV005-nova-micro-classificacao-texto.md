---
type: INV
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
origem: "docs/analysis/CONTEXT001-nova-micro-classificacao-texto.md"
---

# INV005 — `nova-micro` não classifica com confiança transações em texto (pt-BR)

## Contexto

Gatilho: `CONTEXT001-nova-micro-classificacao-texto.md`, descoberto durante teste manual de `TASKS006-sqlite-para-dynamodb.md` (Cenário 1, fluxo de texto) — **não é bug do TASKS006**, é regressão de comportamento introduzida em `TASKS004-gemini-para-bedrock.md` (migração Gemini → Bedrock), que trocou o modelo de classificação de texto.

Branch atual: `feat/sqlite-para-dynamodb` (working tree limpo). Esta task deve virar sua própria branch antes de qualquer código, por convenção do `CLAUDE.md` (sugestão: `feat/nova-lite-texto` ou `fix/nova-micro-classificacao-texto`).

## Problema — `nova-micro` classifica "é transação?" de forma não-confiável

### Descrição observada

`services/nlp_service.py` → `BedrockProvider.extract_text_transactions` (`services/llm/bedrock_provider.py:16`, `TEXT_MODEL_ID = "us.amazon.nova-micro-v1:0"`) classifica incorretamente mensagens de texto que descrevem claramente uma transação, retornando `e_transacao: false` para casos como `"gastei 10 reais no mercado"`. O usuário recebe "Não foi identificada nenhuma transação nessa mensagem" mesmo com frase inequívoca.

### Análise de causa raiz

`nova-micro` não é confiável para a tarefa de classificação binária "é ou não uma transação financeira" em português a partir de frases curtas. **Não é problema de prompt nem de código**:

1. **Não-determinismo com temperatura padrão** (`inferenceConfig` sem `temperature` explícito, estado atual de produção): o mesmo input (`"Gastei 10 reais no mercado"`) chamado 4x seguidas retornou `true, false, false, false` — variância pura de amostragem, sem qualquer mudança no texto de entrada.
2. **`temperature: 0` (decodificação gulosa) não resolve** — fica determinístico por input, mas o resultado "mais provável" muda com variações mínimas de texto, sem padrão sensato:
   - `"gastei 15 reais no mercado"` → `true`; `"gastei 20 reais no mercado"` → `false`; `"gastei 25 reais no mercado"` → `true`.
   - `"gastei 10 reais no mercado"`, `"gastei 10 reais na padaria"`, `"gastei 50 reais na padaria"`, `"gastei 10 reais no cinema"`, `"gastei 50 reais no cinema"`, `"comprei pão por 5 reais"` → todos `false` (deveriam ser `true`).
   - `"recebi 100 reais de salario"`, `"paguei 20 reais de uber"` → `true` (corretos).
3. **A/B contra `nova-lite`** (`us.amazon.nova-lite-v1:0`, já usado hoje em `DOCUMENT_MODEL_ID` para foto/PDF, confirmado funcionando pelo usuário em teste manual real): os mesmos 5 inputs que falhavam em `nova-micro` classificaram **corretamente e de forma consistente** com `nova-lite`, mesmo prompt (`build_text_extraction_prompt`, `prompts.py:6`), `temperature: 0`.

Prompt usado nos testes: exatamente `build_text_extraction_prompt()` de `prompts.py`, sem modificação.

### Arquivos relevantes (estado atual, literal)

**`services/llm/bedrock_provider.py`** (linhas 13-16, constantes de modelo):
```python
REGION = "us-east-2"
TEXT_MODEL_ID = "us.amazon.nova-micro-v1:0"
DOCUMENT_MODEL_ID = "us.amazon.nova-lite-v1:0"
```

**`services/llm/bedrock_provider.py`** (linhas 93-102, `_call_with_malformed_retry` — ponto que faz `json.loads` direto na resposta):
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

**`services/llm/bedrock_provider.py`** (linhas 62-66, chamada de texto):
```python
async def extract_text_transactions(self, text: str) -> list[Transacao]:
    prompt = build_text_extraction_prompt(date.today().isoformat(), text)
    messages = [{"role": "user", "content": [{"text": prompt}]}]
    return await self._call_with_malformed_retry(TEXT_MODEL_ID, messages, self._parse_text_response)
```

### Pegadinha identificada para a correção (verificada, não é suposição)

`nova-lite` envolve a resposta em bloco markdown ```` ```json ... ``` ````, diferente de `nova-micro` (que responde JSON cru). `_call_with_malformed_retry` faz `json.loads(text)` direto sobre o texto bruto retornado por `_converse_with_retry`. Trocar só `TEXT_MODEL_ID` sem ajustar o parser troca uma falha (classificação errada, sem exceção) por outra (`BedrockOutputError` em **toda** chamada de texto, já que `json.loads` falha no `` ```json `` inicial, esgota a re-tentativa e levanta). Qualquer correção precisa tornar o parsing tolerante a esse cercamento (`strip` de ```` ```json ```` / ```` ``` ```` antes do `json.loads`), coberto por TDD com os dois formatos (com e sem cercamento) — não assumir que todo modelo futuro responde igual.

Teste existente que documenta o comportamento hoje e que quebraria sem o ajuste do parser: `tests/services/llm/test_bedrock_provider.py::test_malformed_output_retries_once_and_succeeds_on_second_attempt` (usa `_response("isso não é JSON")` como caso de falha — o cercamento markdown de `nova-lite` cai nessa mesma categoria de "JSON malformado" hoje, precisa passar a ser tratado como válido).

### Custo Bedrock verificado (`us-east-2`, on-demand)

Pricing por 1.000 tokens (fonte: AWS Bedrock pricing, cross-checado em duas fontes independentes — não há quebra pública por região `us-east-2` especificamente nas fontes consultadas; pricing on-demand da Nova family é historicamente uniforme entre `us-east-1`/`us-east-2`/`us-west-2`, mas isso **não foi confirmado num texto oficial da AWS específico para `us-east-2`** — verificar `aws.amazon.com/bedrock/pricing` antes de assumir se isso for crítico):

| Modelo | Input / 1k tokens | Output / 1k tokens |
|---|---|---|
| `nova-micro` | $0.000035 | $0.00014 |
| `nova-lite` | $0.00006 | $0.00024 |

`nova-lite` custa ~1,7x mais que `nova-micro` nos dois eixos. Em termos absolutos, para um prompt de classificação de texto curto (algumas centenas de tokens de input, poucas dezenas de output), a diferença é frações de centavo por milhar de mensagens — **não é bloqueio prático** dado o volume atual do bot (uso pessoal, não escala de produção).

## Relação com CONTEXT002 / INV006

Mesma classe de instabilidade documentada em `INV006-nova-lite-extracao-documento-nao-deterministica.md` (variância de amostragem de modelos Nova em tarefas de classificação/extração), mas aqui restrita à classificação binária de texto avulso (`e_transacao: true|false`), não ao fluxo principal de extrato (foto/PDF). São dois problemas independentes, sem dependência de implementação entre si — podem ser corrigidos em qualquer ordem.

## Perguntas em Aberto

Nenhuma — custo verificado (negligível), causa raiz fechada (variância do `nova-micro`, não é prompt/código), solução única já validada por A/B real (`nova-lite` classifica corretamente e consistentemente os mesmos inputs).

## Próximos Passos

Causa raiz fechada, abordagem única sem trade-off remanescente, decisão não é herdada por tasks futuras além do broadcast já existente em `PATTERNS.md` (Nova family em `us-east-2` precisa de inference profile — já documentado). **Classificação: Design Conhecido.**

Rota proposta: **rota curta** — INV005 (este documento) → `TASKS007-nova-lite-classificacao-texto.md`, com a "Decisão de Design" (trocar `TEXT_MODEL_ID` para `nova-lite` + tornar o parser tolerante a cercamento markdown) referenciando este INV.

⏸ Aguardando confirmação do usuário sobre a classificação antes de escrever o TASKS.
