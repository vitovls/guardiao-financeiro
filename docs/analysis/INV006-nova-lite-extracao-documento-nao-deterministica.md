---
type: INV
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
origem: "docs/analysis/CONTEXT002-nova-lite-extracao-documento-nao-deterministica.md"
---

# INV006 — `nova-lite` não extrai PDF de extrato de forma determinística, quebra o dedup na prática

## Contexto

Gatilho: `CONTEXT002-nova-lite-extracao-documento-nao-deterministica.md`, descoberto durante teste manual de `TASKS006-sqlite-para-dynamodb.md` (Cenário 4, envio do mesmo PDF de extrato bancário real duas vezes seguidas).

Branch atual: `feat/sqlite-para-dynamodb` (working tree limpo). Esta task deve virar sua própria branch antes de qualquer código, por convenção do `CLAUDE.md`.

**Não é bug em `repository/dedup.py`/`repository/dynamo_repository.py`** — a lógica de dedup (fingerprint, `sortKey`, `is_similar`) está correta e coberta por teste (`tests/repository/test_dedup.py`, `tests/repository/test_dynamo_repository.py`). O problema é rio acima: a extração via `services/ocr_service.py` → `BedrockProvider.extract_document_transactions` não é determinística o suficiente para alimentar um dedup baseado em fingerprint de texto.

## Problema — extração de documento varia em contagem e em nível de detalhe entre chamadas idênticas

### Descrição observada

Ao enviar o mesmo PDF de extrato bancário duas vezes seguidas: no primeiro envio, vários registros vieram como `⚠️ duplicata_exata` sem serem duplicatas reais; no segundo envio (reenvio do mesmo PDF), quase tudo foi salvo como `🟡 suspeita`, aparentemente só por coincidir a data, não por semelhança real de descrição.

### Evidência coletada (chamada real ao Bedrock, mesmo PDF, duas vezes seguidas, sem tocar em Dynamo)

- **Contagem de transações extraídas diverge**: rodada 1 extraiu **24** transações, rodada 2 extraiu **26**, do mesmo arquivo PDF, sem nenhuma mudança.
- **Descrição varia em nível de detalhe para a mesma transação real** (mesma `data`/`valor`/`tipo` entre as duas rodadas), ex.:
  - Rodada 1: `"Transferência recebida pelo Pix JOSE VICTOR MACEDO VELOSO - ***052.613.-* - 24776-6 BCO DO BRASIL S.A. (0001) Agência: 4710 Conta: 24776-6"`
  - Rodada 2 (mesma transação real): `"Transferência recebida pelo Pix"`
  - `is_similar()` (`repository/dedup.py:20`, `SIMILARITY_THRESHOLD = 0.8`) entre as duas versões: **`False`** (abaixo do threshold) em 5/5 casos amostrados de mesma `(data, valor, tipo)` com descrição divergente.

### Análise de causa raiz

`nova-lite`, no prompt de extração de documento (`build_document_extraction_prompt`, `prompts.py:14`), não é determinístico o bastante: nem a quantidade de itens extraídos nem o nível de detalhe da descrição de cada item se mantêm estáveis entre chamadas idênticas. Isso quebra a premissa de que o dedup por fingerprint (`sha256(valor+tipo+descrição_normalizada)[:16]`, `repository/dedup.py:15-17`) e por similaridade de descrição (`SequenceMatcher`, `repository/dedup.py:20`) funciona de forma previsível sobre extrações reais — mesma classe de instabilidade documentada em `INV005-nova-micro-classificacao-texto.md`, mas aqui afetando o fluxo principal (extrato bancário via PDF/foto), não só texto avulso.

**Consequência prática, sem correção**: reenviar o mesmo extrato pode (a) criar duplicatas silenciosas reais no banco quando a descrição varia o bastante para não bater nem `DUPLICATA_EXATA` nem `SUSPEITA`, ou (b) sinalizar `SUSPEITA`/`DUPLICATA_EXATA` em transações genuinamente diferentes que por acaso coincidiram em `(data, valor, tipo, descrição normalizada)` numa extração específica.

### Arquivos relevantes (estado atual, literal)

**`services/llm/bedrock_provider.py`** (linhas 30-34, chamada Bedrock hoje sem `temperature` explícito):
```python
async def _converse_with_retry(client, model_id: str, messages: list[dict]) -> str:
    for attempt in range(_MAX_ATTEMPTS):
        try:
            response = client.converse(
                modelId=model_id,
                messages=messages,
                inferenceConfig={"maxTokens": _MAX_OUTPUT_TOKENS},
            )
```
Nenhum `temperature` é passado — usa o default do modelo (não-zero), tanto para texto quanto para documento (mesma função serve os dois `model_id`).

**`prompts.py`** (linhas 14-18, prompt de extração de documento, sem instrução sobre nível de detalhe da descrição):
```python
def build_document_extraction_prompt(document_label: str) -> str:
    return (
        f"Extraia as transações deste(a) {document_label} de extrato bancário. "
        f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"
    )
```

**`repository/dedup.py`** (arquivo inteiro, 21 linhas — lógica de dedup determinística, não é o problema, mas é o consumidor afetado):
```python
import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.8
SUSPECT_WINDOW_DAYS = 90


def normalize_description(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def compute_fingerprint(valor: float, tipo: str, descricao_normalizada: str) -> str:
    raw = f"{valor:.2f}|{tipo}|{descricao_normalizada}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD
```

Padrão estabelecido em `PATTERNS.md` ("Dedup determinística: fingerprint no `sortKey`, nunca em atributo próprio") — qualquer mudança de contrato aqui (ex.: tirar a descrição do fingerprint) é uma decisão de produto que reabre `SPEC006`/`PLN006`, não um ajuste incremental.

## Decisão de Produto Confirmada (usuário, nesta sessão)

O usuário já decidiu a **ordem de mitigação** a seguir, descartando explicitamente a alternativa de mudar o contrato de fingerprint (opção (c) original do brainstorm) neste momento:

1. Testar `temperature: 0` explícito na chamada de documento (hoje ausente).
2. Se (1) não resolver, testar prompt mais restritivo (ex.: instruir explicitamente a sempre incluir nome completo do remetente/beneficiário, nunca resumir).
3. Se (1)+(2) não resolverem, testar um modelo mais robusto que `nova-lite` para extração de documento.

**Não decidido ainda, e não deve ser inventado no TASKS sem confirmação do usuário:**

- **Critério de aceitação/"funcionou"**: quantas rodadas de teste manual, sobre quantas transações reais, e qual tolerância de variância (contagem de itens e/ou taxa de `is_similar()` batendo entre rodadas) é considerada suficiente para declarar (1) ou (2) bem-sucedido. Isso é uma escolha de produto (o quanto de duplicata/falso-positivo é aceitável num bot de uso pessoal), não uma escolha técnica que a task possa resolver sozinha.
- **Identidade do "modelo mais robusto"** do passo 3, caso necessário (ex.: `nova-pro` — mesma família, natural próximo passo, ~13x mais caro que `nova-lite` por token segundo pricing público — vs. um modelo de outro provedor via Bedrock). Fica para o SPEC/PLN, não é consenso ainda.

## Não investigado ainda

- Não foi confirmado se `temperature: 0` reduz a variância na prática para o caso de **documento** (só foi testado para texto, em `INV005`) — é o passo mais barato e o primeiro da ordem acordada.
- Não foi avaliado se um prompt mais restritivo reduz a variância de verbosidade da descrição.
- Não foi comparado o mesmo teste contra `nova-micro` para extração de documento (tecnicamente suporta imagem/documento; não testado, não é a direção acordada pelo usuário — descartar a menos que (1)+(2)+(3) falhem).

## Relação com INV005

Mesma classe de instabilidade (variância de amostragem de modelos Nova), mas aqui afeta o fluxo principal (extrato via PDF/foto) e tem consequência mais severa (dedup silenciosamente incorreto), enquanto `INV005` afeta só a classificação binária de texto avulso. Problemas independentes, sem dependência de implementação entre si.

## Perguntas em Aberto

1. Critério de aceitação para "a variância foi resolvida" após os passos 1/2 (quantas rodadas, quantas transações de teste, qual tolerância) — não pode ser inventado pelo Claude, precisa vir do usuário no SPEC.
2. Se os passos 1+2 não resolverem, qual modelo usar no passo 3 (`nova-pro` é a sugestão natural, mas não é decisão fechada) — depende também de custo aceitável, a confirmar no PLN.

## Próximos Passos

A ordem de mitigação está decidida, mas o critério de sucesso e o fallback de modelo (passo 3) permanecem em aberto e envolvem trade-off real (tolerância a duplicata vs. esforço de correção vs. custo de modelo mais caro) — decisão que qualquer fase futura de extração de documento herdaria. **Classificação: Ambíguo.**

Rota proposta: **rota completa** — INV006 (este documento) → `SPEC008-nova-lite-extracao-documento.md` (fechar as duas Perguntas em Aberto com o usuário como Critérios de Aceitação) → `PLN008-nova-lite-extracao-documento.md` (estratégia dos 3 passos com Antes/Depois, alternativas de modelo fallback descartadas) → `TASKS008-nova-lite-extracao-documento.md`.

⏸ Aguardando confirmação do usuário sobre a classificação antes de escrever o SPEC.
