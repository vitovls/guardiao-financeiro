---
type: INV
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
origem: docs/analysis/CONTEXT004-nova-lite-extracao-texto-tipo-valor-girias.md
---

# INV007 — `nova-lite` erra tipo/sinal, valor e gírias monetárias na extração de texto

## Contexto

**Gatilho:** descoberto durante teste manual exploratório de `TASKS007-nova-lite-classificacao-texto.md` (fluxo de texto via Telegram, `LLM_PROVIDER=bedrock` real, `nova-lite`), fora dos 7 casos formalmente cobertos pelo `INV005`. Documentado em `docs/analysis/CONTEXT004-nova-lite-extracao-texto-tipo-valor-girias.md`.

**Branch no momento da investigação:** `feat/nova-lite-extracao-documento` (branch do `TASKS008`, ainda não mergeada em `main`). Este INV **não** implementa nada nela — `TASKS009` (artefato seguinte) roda em branch própria, criada a partir de `main` depois do merge de `feat/nova-lite-extracao-documento` (ver "Próximos Passos").

**Escopo:** exclusivamente `services/nlp_service.py` → `BedrockProvider.extract_text_transactions` (`TEXT_MODEL_ID`, hoje `"us.amazon.nova-lite-v1:0"`) e `build_text_extraction_prompt` (`prompts.py`). Não toca `extract_document_transactions`/`DOCUMENT_MODEL_ID` (já resolvido em `TASKS008`, agora `"us.meta.llama4-maverick-17b-instruct-v1:0"`) nem `repository/dedup.py`.

## Problema

`nova-lite` já resolveu o falso-negativo de classificação booleana diagnosticado no `INV005`/`CONTEXT001` (confirmado via A/B em `TASKS007`: mesmo prompt, `nova-lite` acertava onde `nova-micro` errava). Mas variantes de texto mais informais/coloquiais expõem falhas **diferentes**, na extração dos campos (`tipo`, `valor`, `e_transacao`), não só no booleano "é transação?".

### Descrição observada

| Input | Resultado observado | Resultado esperado |
|---|---|---|
| `"Meu salario caiu de 3700 reais"` | Não reconhecida (`e_transacao: false`) | `entrada`, R$3700 |
| `"Salario caiu 3700 reais"` | `saida`, -R$3700 | `entrada`, R$3700 |
| `"Gastei com mercado"` | `saida`, R$0,00 | Ambíguo no `CONTEXT004` — resolvido abaixo (ver "Decisões de Produto Confirmadas") |
| `"Pix de 10 conto caiu aqui"` | `entrada`, R$1000,00 | `entrada`, R$10,00 |
| `"Boleto de 150 venceu hoje"` | `entrada`, R$150,00 | `saida`, R$150,00 |
| `"Estornou 40 conto que cobraram errado oh"` | `entrada`, R$4000,00 | `entrada`, R$40,00 |

Relato do usuário, não reproduzido de forma controlada (sem variação de `temperature`, sem múltiplas rodadas por input, sem comparação A/B de prompt) — decisão do usuário nesta sessão foi **não** investir em reprodução controlada antes de agir (ver "Decisões de Produto Confirmadas").

### Análise de causa raiz

**Não confirmada por experimento controlado** (nenhum A/B rodado para este conjunto de casos, diferente do que foi feito para o booleano em `TASKS007`). Hipóteses levantadas no `CONTEXT004`, sem eliminação entre elas:

- `build_text_extraction_prompt` (`prompts.py:6-14`) não instrui convenções de sinal/tipo por verbo/contexto — nenhuma menção a "caiu" (entrada), "venceu"/"boleto" (saída antes do pagamento).
- Gírias monetárias brasileiras ("conto") não estão documentadas em nenhum lugar do prompt — o modelo aplica uma conversão arbitrária (aparenta ×100 nos 2 casos observados, amostra pequena demais para confirmar padrão).
- Ausência de valor explícito no texto não tem instrução clara — `valor = 0.00` pode ser tanto comportamento aceitável quanto ausência de contrato de produto definido.

**Decisão de produto tomada nesta sessão (ver abaixo): não investigar qual fração é causa de modelo vs. causa de prompt.** O projeto já tem precedente direto em `TASKS008`/`INV006`: duas iterações de prompt mais restritivo (`T3`, `T3b`) falharam em resolver um problema estrutural similar (omissão/alucinação de conteúdo) na extração de documento, e só a troca de modelo (`nova-pro`, depois `meta.llama4-maverick-17b-instruct-v1:0`) resolveu — documentado em `docs/PATTERNS.md` ("Fallback de modelo por robustez..."). O usuário optou por não repetir o ciclo de tentativa-e-erro de prompt e ir direto para a troca de modelo, reaproveitando o modelo já validado em `TASKS008`.

### Arquivos relevantes

- `prompts.py:6-14` — `build_text_extraction_prompt`, sem instrução de sinal/tipo, gíria ou valor implícito.
- `services/llm/bedrock_provider.py:15` — `TEXT_MODEL_ID = "us.amazon.nova-lite-v1:0"`.
- `services/llm/bedrock_provider.py:75-78` — `extract_text_transactions`, chama `_call_with_malformed_retry(TEXT_MODEL_ID, messages, self._parse_text_response)` sem `temperature` (fica `None`, comportamento correto e já testado — não muda neste INV).
- `services/llm/bedrock_provider.py:89-92` — `_parse_text_response`, retorna lista vazia se `e_transacao` for falsy, senão instancia `Transacao(**item)` por item de `transacoes`.
- `models.py:9-19` — `Transacao`, `valor: float` sem validação/default (diferente de `categoria`, que tem `field_validator` com `DEFAULT_CATEGORIA`). Nenhum tratamento estrutural equivalente existe hoje para `valor == 0.0`.
- `services/message_service.py:26-62` — `format_message`, já tem o padrão de nota inline para `categoria == DEFAULT_CATEGORIA` (linha 51-52) — precedente direto a seguir para o alerta de valor ausente.
- `scripts/aws/iam-policy-guardiao-dev.json` — já contém as 4 entradas de ARN de `meta.llama4-maverick-17b-instruct-v1:0` (2 no `Statement` de inference profile/foundation model), aplicadas e confirmadas em `TASKS008` T7. **Nenhuma mudança de IAM necessária neste INV** — o modelo já está autorizado para a conta.

### Relação entre os problemas

Os 4 sintomas (falso negativo remanescente, sinal/tipo trocado, valor implícito ausente, gíria mal convertida) compartilham a mesma superfície de causa: nenhum deles tem instrução explícita no prompt, e nenhum foi testado com o modelo que já provou ser mais robusto para extração semântica (`meta.llama4-maverick-17b-instruct-v1:0`, `TASKS008`). Não é a mesma causa raiz do `INV005` (aquele era especificamente sobre o booleano `e_transacao` em frases diretas, confirmado como limitação de `nova-micro`, não de prompt).

## Decisões de Produto Confirmadas (usuário, nesta sessão)

1. **Modelo:** trocar `TEXT_MODEL_ID` para `"us.meta.llama4-maverick-17b-instruct-v1:0"` (mesmo valor de `DOCUMENT_MODEL_ID` pós-`TASKS008`). Decisão explícita de pular o próximo tier Nova (`nova-pro`) — a regra registrada em `docs/PATTERNS.md` ("Fallback de modelo por robustez segue a mesma família Nova antes de trocar de provedor") é superada aqui pela mesma razão que já a superou em `TASKS008` v1.2.0: o modelo já está validado no projeto para extração financeira semanticamente mais exigente, e o objetivo explícito do usuário é evitar o ciclo de ajuste de prompt sem necessidade.
2. **Sem reprodução controlada prévia:** os 6 casos do `CONTEXT004` são o baseline. Não rodar múltiplas repetições em `nova-lite` antes de trocar — ir direto para comparação A/B dos mesmos 6 casos contra o modelo novo.
3. **Gíria "conto":** 1 conto = R$1 (uso tradicional/mais comum no português do Brasil). `"10 conto"` → R$10,00, não R$1000,00.
4. **Valor ausente/implícito** (ex.: `"Gastei com mercado"`): mantém `valor = 0.0`, mas passa a **alertar o usuário inline**, seguindo o mesmo princípio já estabelecido para `categoria` vazia (`DEFAULT_CATEGORIA` + nota em `format_message`, `docs/PATTERNS.md` linha 105-107) — não descartar a transação, não pedir confirmação com espera de resposta (mesmo princípio "sem estado" já usado no projeto).
5. **Decisão herdável / generalização:** esta troca estabelece Llama 4 Maverick como modelo padrão para extração via LLM no projeto — texto e documento —, não uma decisão isolada do fluxo de texto. Vai para broadcast em `docs/PATTERNS.md` no artefato seguinte.

## Perguntas em Aberto

Nenhuma — todas as lacunas do `CONTEXT004` (convenção de gíria, comportamento de valor ausente, escolha de modelo, necessidade de reprodução controlada, escopo do padrão) foram resolvidas nesta sessão (ver "Decisões de Produto Confirmadas").

## Próximos Passos

**Rota curta (Design Conhecido):** a causa raiz estrutural está fechada (ausência de instrução no prompt + modelo testado é o próximo passo natural, sem alternativa em aberto) e todas as decisões de produto foram tomadas diretamente pelo usuário nesta sessão, sem trade-off remanescente. `SPEC`/`PLN` não são necessários — segue direto para `TASKS009`, com a solução documentada como "Decisão de Design" referenciando este INV.

**Pré-requisito de branch:** `feat/nova-lite-extracao-documento` (`TASKS008`) precisa estar mergeada em `main` antes de criar a branch desta task — mesmo padrão de pré-requisito já usado entre `TASKS007`→`TASKS008`. Branch nova: `feat/llama-maverick-extracao-texto`, criada a partir de `main` pós-merge.
