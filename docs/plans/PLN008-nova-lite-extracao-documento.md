---
type: PLN
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
inv: docs/analysis/INV006-nova-lite-extracao-documento-nao-deterministica.md
spec: docs/specs/SPEC008-nova-lite-extracao-documento.md
---

# PLN008 — Reduzir não-determinismo da extração de documento (`nova-lite`)

## Contexto

Ver `INV006` (diagnóstico) e `SPEC008` (requisitos: 3 mitigações condicionais, parando na primeira que satisfizer o critério de 3 rodadas idênticas). Este documento resolve o "como" de cada passo e compara as alternativas de modelo fallback (passo C), deixado em aberto pelo SPEC.

## Estratégia

### A. `temperature=0` explícito na chamada de documento

**Antes** (`services/llm/bedrock_provider.py`, `_converse_with_retry`, linhas 30-47 — sem `temperature`, função compartilhada por texto e documento):
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
        ...
```

**Depois** — parâmetro opcional `temperature`, só passado pela chamada de documento (A2/D2 do SPEC exigem não tocar o fluxo de texto):
```python
async def _converse_with_retry(client, model_id: str, messages: list[dict], temperature: float | None = None) -> str:
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
        ...
```

`extract_document_transactions` passa `temperature=0.0` explicitamente; `extract_text_transactions` não passa nada (mantém o comportamento hoje, `temperature=None` → chave omitida, igual ao estado atual — nenhuma regressão no fluxo de texto, satisfaz A2/D2 do SPEC).

**Por que thread via parâmetro em vez de duplicar `_converse_with_retry`:** a função já é pequena e o retry/backoff (throttling, timeout) é idêntico nos dois casos de uso — duplicar só pra variar um parâmetro violaria "três linhas parecidas são melhores que abstração prematura" ao contrário (aqui a abstração já existe e é a duplicação que seria o erro).

### B. Prompt mais restritivo (só se A não resolver)

**Antes** (`prompts.py`, `build_document_extraction_prompt`, linhas 14-18):
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
`build_text_extraction_prompt` não é tocado (B2 do SPEC) — os dois prompts já são funções independentes em `prompts.py`, sem acoplamento.

### C. Modelo alternativo (só se A+B não resolverem) — comparação

Duas alternativas plausíveis, ambas invocáveis via o mesmo `_converse_with_retry`/Converse API (satisfaz C2 do SPEC, sem nova SDK):

| Opção | Model ID (a confirmar) | Preço aprox. (input/output por 1M tokens) | Prós | Contras |
|---|---|---|---|---|
| **`nova-pro`** (recomendado) | `us.amazon.nova-pro-v1:0` | ~$0,80 / $3,20 | Mesma família Nova, mesmo padrão de inference profile já documentado em `PATTERNS.md` (`us-east-2` → `us-east-1`/`us-east-2`/`us-west-2`); só precisa de mais uma entrada na IAM policy existente (mesmo `Sid`-pattern do `nova-micro`/`nova-lite`); tier "Pro" da mesma linha é o próximo passo natural de robustez. | ~13x mais caro que `nova-lite` por token; ainda não testado neste projeto para extração de documento — precisa de validação manual antes de assumir que resolve. |
| Claude Haiku (via Bedrock) | a confirmar (ex. `us.anthropic.claude-haiku-*`) | ~$1,00 / $5,00 | Reputação forte em extração de documento/visão; ainda dentro do Bedrock (não é um provider novo). | Preço similar ou levemente maior que Nova Pro; exige nova entrada de ARN de foundation-model (`anthropic.*`) na IAM policy, região/inference-profile ainda não confirmados para este projeto; sai da família Nova já validada operacionalmente (`INV001`/`PATTERNS.md`). |

**Preços acima são estimativas de pesquisa web em 2026, não confirmadas na página oficial `aws.amazon.com/bedrock/pricing` no momento da escrita deste PLN — confirmar o valor exato e a disponibilidade do model ID em `us-east-2` antes de implementar C, por `CLAUDE.md` ("verificar contra documentação, não assumir").**

**Decisão:** se o passo C for necessário, tentar `nova-pro` primeiro — menor mudança operacional (mesma família, mesmo padrão de IAM/inference-profile já em produção), custo ainda irrelevante em termos absolutos para o volume do bot (uso pessoal, poucos extratos/mês). Claude Haiku fica registrado como alternativa descartada nesta rodada, não eliminada permanentemente — se `nova-pro` também falhar no critério de aceitação, reabrir a comparação antes de tentar Claude (fora do escopo de `TASKS008`, viraria uma nova iteração de `/map-task`).

### D. `DOCUMENT_MODEL_ID` — troca (só se C for alcançado)

**Antes** (`services/llm/bedrock_provider.py`, linha 15):
```python
DOCUMENT_MODEL_ID = "us.amazon.nova-lite-v1:0"
```

**Depois** (só se A+B não resolverem):
```python
DOCUMENT_MODEL_ID = "us.amazon.nova-pro-v1:0"
```

Nenhuma outra mudança de código necessária — `_call_with_malformed_retry` e `_strip_markdown_fence` (já implementados em `TASKS007`) continuam funcionando sem alteração (C3 do SPEC).

## Arquivos a Modificar

- `services/llm/bedrock_provider.py` — A (parâmetro `temperature`), D (constante `DOCUMENT_MODEL_ID`, só se C for alcançado).
- `prompts.py` — B (`build_document_extraction_prompt`), só se A não resolver.
- `scripts/aws/iam-policy-guardiao-dev.json` — nova entrada de ARN para `nova-pro` (mesmo padrão de `nova-micro`/`nova-lite`), só se C for alcançado.
- `tests/services/llm/test_bedrock_provider.py` — teste novo para A (temperature passado corretamente); nenhuma mudança de teste esperada para B/C além de atualizar a constante de modelo esperada, se chegarem a ser implementados.
- `docs/PATTERNS.md` — broadcast só se C for alcançado (padrão de fallback de modelo Nova por robustez, reaproveitável por fases futuras).

## Riscos

- **`temperature=0` reduzir a "criatividade" de formatação e ainda assim não resolver a variância** — mitigado pelo próprio desenho em passos: se não resolver, B/C seguem, sem re-trabalho (A não é descartado, continua ativo nos passos seguintes).
- **Nova Pro (se necessário) aumentar custo de forma perceptível** — mitigado por ser fallback de último recurso, usado só no fluxo de documento (baixo volume, extratos enviados esporadicamente, não é o fluxo de texto de alta frequência).
- **Preços/model IDs da tabela C desatualizados** — mitigado exigindo confirmação na doc oficial da AWS antes de implementar D, não antes (A e B não dependem dessa informação).
- **Teste manual de 3 rodadas ser caro/lento de repetir a cada mitigação** — aceito conscientemente: é o mesmo padrão de teste manual já usado no projeto para chamadas reais de LLM (`CLAUDE.md`), e o critério (3 rodadas, mesmo PDF) já está fixado no SPEC para não virar um teste movediço.

## Alternativas Descartadas

- **Mudar o contrato de fingerprint (tirar a descrição)** — descartada explicitamente pelo usuário no `/map-task` (ver `INV006`, Decisão de Produto Confirmada); reabriria `SPEC006`/`PATTERNS.md` sem necessidade, dado que as mitigações A-C atacam a causa raiz (variância do modelo) em vez do sintoma (fingerprint sensível a variância).
- **Pular direto para troca de modelo (C) sem testar A/B** — descartada pelo usuário (ordem de mitigação decidida: barato/reversível primeiro). Também evita gastar mais (Nova Pro é ~13x mais caro) antes de esgotar as opções de configuração.
- **Testar `nova-micro` para documento** — mencionado como não investigado no `INV006`, mas descartado como direção: `nova-micro` já provou ser o modelo menos confiável do trio para tarefas de classificação/extração (`INV005`), não há razão para esperar melhor determinismo nele para uma tarefa ainda mais complexa (extração multi-item de documento).

## Validação Final (contra o SPEC008)

- [ ] Critério de aceitação (3 rodadas do mesmo PDF real, contagem idêntica + `is_similar()` em todas as correspondências) satisfeito em algum ponto de parada (A, B, ou C).
- [ ] Nenhuma mudança de comportamento observável no fluxo de texto (`extract_text_transactions`).
- [ ] Nenhuma mudança no contrato de dedup (`repository/dedup.py`).
- [ ] `pytest` 100% verde, sem chamada real a Bedrock em teste automatizado.
- [ ] Se C foi alcançado: IAM policy e `PATTERNS.md` atualizados; model ID e preço confirmados contra a documentação oficial da AWS antes do commit.
