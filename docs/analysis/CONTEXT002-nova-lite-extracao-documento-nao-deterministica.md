---
type: CONTEXT
version: 1.0.0
author: Victor Veloso
date: 2026-07-27
status: Draft
origem: "Descoberto durante teste manual de TASKS006-sqlite-para-dynamodb.md (Cenário 4, envio de PDF de extrato bancário real, duas vezes seguidas)"
---

# CONTEXT002 — `nova-lite` não extrai PDF de extrato de forma determinística, quebra o dedup na prática

## Problema

Ao enviar o mesmo PDF de extrato bancário duas vezes seguidas: no primeiro envio, vários registros vieram como `⚠️ duplicata_exata` sem serem duplicatas reais; no segundo envio (reenvio do mesmo PDF), quase tudo foi salvo como `🟡 suspeita`, aparentemente só por coincidir a data, não por semelhança real de descrição.

**Não é bug em `repository/dedup.py`/`repository/dynamo_repository.py`** — a lógica de dedup (fingerprint, `sortKey`, `is_similar`) está correta e coberta por teste (`tests/repository/test_dynamo_repository.py`, `tests/repository/test_sqlite_repository.py`). O problema é rio acima: a extração via `services/ocr_service.py` → `BedrockProvider.extract_document_transactions` (`DOCUMENT_MODEL_ID = "us.amazon.nova-lite-v1:0"`) não é determinística o suficiente pra alimentar um dedup baseado em fingerprint de texto.

## Evidência coletada (chamada real ao Bedrock, mesmo PDF, duas vezes seguidas, sem tocar em Dynamo)

- **Contagem de transações extraídas diverge**: rodada 1 extraiu **24** transações, rodada 2 extraiu **26**, do mesmo arquivo PDF, sem nenhuma mudança.
- **Descrição varia em nível de detalhe para a mesma transação real** (mesma `data`/`valor`/`tipo` entre as duas rodadas), ex.:
  - Rodada 1: `"Transferência recebida pelo Pix JOSE VICTOR MACEDO VELOSO - ***052.613.-* - 24776-6 BCO DO BRASIL S.A. (0001) Agência: 4710 Conta: 24776-6"`
  - Rodada 2 (mesma transação real): `"Transferência recebida pelo Pix"`
  - `is_similar()` entre as duas versões: **`False`** (abaixo do threshold 0.8) em 5/5 casos amostrados de mesma `(data, valor, tipo)` com descrição divergente.

## Causa raiz

`nova-lite`, no prompt de extração de documento (`build_document_extraction_prompt`, `prompts.py`), não é determinístico o bastante: nem a quantidade de itens extraídos nem o nível de detalhe da descrição de cada item se mantêm estáveis entre chamadas idênticas. Isso quebra a premissa de que o dedup por fingerprint (`sha256(valor+tipo+descrição_normalizada)`) e por similaridade de descrição (`SequenceMatcher`) funciona de forma previsível sobre extrações reais — mesma classe de instabilidade documentada em `CONTEXT001-nova-micro-classificacao-texto.md`, mas aqui afetando o fluxo principal (extrato bancário via PDF/foto), não só texto avulso.

**Consequência prática, sem correção**: reenviar o mesmo extrato pode (a) criar duplicatas silenciosas reais no banco quando a descrição varia o bastante pra não bater nem `DUPLICATA_EXATA` nem `SUSPEITA`, ou (b) sinalizar `SUSPEITA`/`DUPLICATA_EXATA` em transações genuinamente diferentes que por acaso coincidiram em `(data, valor, tipo, descrição normalizada)` numa extração específica.

## Não investigado ainda (próximos passos pra quem pegar isso)

- Não foi confirmado se `inferenceConfig.temperature` explícito (hoje ausente na chamada de documento, igual ao caso do texto) reduziria a variância — vale testar `temperature: 0` no `_converse_with_retry` de `extract_document_transactions` primeiro, é a mudança mais barata.
- Não foi avaliado se um prompt mais restritivo (ex.: instruir explicitamente "sempre inclua nome completo do remetente/beneficiário na descrição, nunca resuma") reduz a variância de verbosidade da descrição.
- Alternativa de design a considerar: basear o fingerprint em campos mais estáveis do extrato (ex.: valor + data + tipo apenas, sem descrição, já que descrição é o campo mais sujeito a variação do LLM) — mas isso é uma mudança de contrato do SPEC006/PLN006 (decisão vinculante 1), precisa de nova rodada de decisão de produto, não só código.
- Não foi comparado o mesmo teste contra `nova-micro` para extração de documento (`nova-micro` tecnicamente suporta imagem/documento) — poderia ser pior ou melhor, não testado.

## Recomendação

Investigar como task própria (`/map-task`), fora do escopo de `TASKS006`. Prioridade sugerida alta — afeta diretamente a confiabilidade do fluxo principal do bot (registrar transações via extrato/foto), não é um caso de borda.
