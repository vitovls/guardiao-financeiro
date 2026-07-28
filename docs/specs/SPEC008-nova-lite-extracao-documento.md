---
type: SPEC
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
inv: docs/analysis/INV006-nova-lite-extracao-documento-nao-deterministica.md
---

# SPEC008 — Reduzir não-determinismo da extração de documento (`nova-lite`)

## Intenção

Fazer a extração de transações de extrato bancário (PDF/foto, `BedrockProvider.extract_document_transactions`) produzir resultados estáveis o bastante entre chamadas idênticas para que o dedup por fingerprint (`repository/dedup.py`, contrato já fechado em `SPEC006`) funcione na prática. Hoje reenviar o mesmo extrato pode gerar contagens diferentes de transações e descrições com nível de detalhe variável, quebrando tanto `DUPLICATA_EXATA` quanto `SUSPEITA` (ver `INV006`). Esta fase testa mitigações em ordem crescente de custo/invasividade, sem alterar o contrato de dedup.

## Contexto

Ver `docs/analysis/INV006-nova-lite-extracao-documento-nao-deterministica.md` para o diagnóstico completo (evidência real: 24 vs. 26 transações extraídas do mesmo PDF em duas rodadas; descrições da mesma transação real variando de detalhada a genérica o bastante para `is_similar()` retornar `False`).

Das Perguntas em Aberto do INV, ambas resolvidas nesta sessão com o usuário:

1. **Critério de aceitação** ("a variância foi resolvida"): mesmo PDF real usado no `INV006`, extraído 3 vezes seguidas — contagem de transações idêntica nas 3 rodadas, e toda transação real correspondente entre rodadas passa em `is_similar()` (≥ 0.8, threshold já existente em `repository/dedup.py`). Ver Critérios de Aceitação abaixo.
2. **Modelo de fallback** (passo 3, caso temperature/prompt não resolvam): **não decidido** — fica para o PLN008 comparar alternativas (ex. `nova-pro` vs. outro modelo disponível via Bedrock) com custo e trade-offs explícitos antes de escolher.

Decisão de produto já confirmada (herdada do `INV006`, vinculante): o contrato de dedup (`fingerprint` incluindo descrição normalizada, `PATTERNS.md` → "Dedup determinística") **não muda** nesta fase — nenhuma alternativa que rediscuta B1-B3b de `SPEC006` é aceitável aqui.

## Requisitos (EARS)

### A. Mitigação em ordem — temperatura determinística primeiro

- A1. O sistema deve chamar o Bedrock Converse API para extração de documento (`extract_document_transactions`) com `temperature` explícito igual a `0` (decodificação gulosa), em vez de depender do default do modelo.
- A2. A mudança de A1 não deve alterar o comportamento da extração de **texto** (`extract_text_transactions`) — escopo desta fase é só o fluxo de documento; texto já foi resolvido em `TASKS007` por troca de modelo, sem necessidade de `temperature` explícito.
- A3. Se, após A1, o critério de aceitação (seção "Critérios de Aceitação") for satisfeito em teste manual, as mitigações B e C abaixo **não** precisam ser implementadas — a task termina em A1.

### B. Mitigação em ordem — prompt mais restritivo (só se A não resolver)

- B1. Se A1 sozinho não satisfizer o critério de aceitação, o sistema deve usar um prompt de extração de documento (`build_document_extraction_prompt`, `prompts.py`) que instrua explicitamente o modelo a sempre incluir o nome completo do remetente/beneficiário e detalhes de conta na descrição de cada transação, nunca resumindo ou omitindo esses dados mesmo quando o extrato repetir informação.
- B2. A mudança de B1 não deve alterar o prompt de extração de **texto** (`build_text_extraction_prompt`) — prompts diferentes para os dois casos de uso, sem acoplamento entre eles (já é o desenho atual de `prompts.py`).
- B3. Se, após A1+B1, o critério de aceitação for satisfeito em teste manual, a mitigação C abaixo **não** precisa ser implementada.

### C. Mitigação em ordem — modelo mais robusto (só se A+B não resolverem)

- C1. Se A1+B1 juntos não satisfizerem o critério de aceitação, o sistema deve substituir `DOCUMENT_MODEL_ID` por um modelo alternativo, mantendo o mesmo contrato de `LLMProvider`/`BedrockProvider` (sem introduzir uma nova abstração de provider) — a identidade do modelo alternativo é decisão do PLN008 (comparação de custo/qualidade), não deste SPEC.
- C2. Qualquer modelo alternativo escolhido em C1 deve continuar sendo invocado via `boto3` Bedrock Converse API (`_converse_with_retry`), sem exigir uma nova SDK ou cliente.
- C3. A troca de modelo em C1 deve reutilizar a proteção de cercamento markdown já implementada em `TASKS007` (`_strip_markdown_fence`) — qualquer modelo Bedrock pode ou não cercar a resposta, o parser já é tolerante a ambos os casos.

### D. Invariantes (não mudam nesta fase)

- D1. O sistema não deve alterar o contrato de dedup (`repository/dedup.py`: `compute_fingerprint`, `normalize_description`, `is_similar`, `SIMILARITY_THRESHOLD`) — nenhuma mitigação desta fase depende de mudar o que entra no fingerprint.
- D2. O sistema não deve alterar `TEXT_MODEL_ID` nem o comportamento de `extract_text_transactions` — escopo fechado em `TASKS007`.
- D3. Cada mitigação (A, depois B, depois C) deve ser implementada e testada manualmente **antes** de decidir se a próxima é necessária — não implementar B ou C especulativamente sem confirmar que a mitigação anterior falhou no critério de aceitação.

## Non-Goals (fora de escopo desta fase)

- Mudar o contrato de fingerprint/dedup (`SPEC006`) — decisão de produto já fechada, não revisitada aqui mesmo que resolvesse o sintoma mais diretamente.
- Qualquer mudança no fluxo de texto (`nova-micro`/`nova-lite`, `TASKS007`) — task independente, já concluída ou em andamento separadamente.
- Introduzir uma nova abstração de provider (ex. multi-provider dentro de `BedrockProvider`) — a troca de modelo em C, se necessária, é só uma troca de constante + prompt, permanece dentro de `BedrockProvider`.
- Otimizar custo do Bedrock de forma geral — o PLN008 confirma que o modelo de fallback escolhido (se chegar a C) tem custo aceitável para o volume atual do bot (uso pessoal), mas não é uma revisão de custo abrangente do projeto.
- Automação do teste de variância (ex. rodar N extrações e comparar programaticamente) — os testes desta fase são manuais, com LLM real, seguindo a regra já estabelecida no `CLAUDE.md` ("chamadas reais a LLM/AWS nunca entram em teste automatizado").

## Critérios de Aceitação

1. **Critério de sucesso de cada mitigação (A, B, ou C):** extrair o mesmo PDF real usado em `INV006` três vezes seguidas, sem nenhuma mudança de arquivo ou input entre as rodadas. Sucesso significa: (a) a contagem de transações extraídas é idêntica nas 3 rodadas, e (b) para cada transação real que aparece nas 3 rodadas, a descrição extraída em rodadas diferentes passa em `is_similar()` (`repository/dedup.py`, threshold ≥ 0.8) quando comparada par a par.
2. Se A1 (temperature=0) sozinho satisfizer o critério 1, `TASKS008` termina ali — nenhum código de B ou C é escrito.
3. Se A1 não satisfizer o critério 1, B1 (prompt mais restritivo) é implementado e o mesmo teste do critério 1 é repetido: se passar, `TASKS008` termina em B — C não é implementado.
4. Se A1+B1 não satisfizerem o critério 1, C1 (modelo alternativo, escolhido no PLN008) é implementado e o mesmo teste do critério 1 é repetido como validação final.
5. Em qualquer ponto de parada (A, B, ou C), a suíte `pytest` continua 100% verde e nenhum teste automatizado passou a depender de chamada real ao Bedrock.
6. O fluxo de texto (`extract_text_transactions`) não sofre nenhuma mudança de comportamento observável como efeito colateral desta fase.
