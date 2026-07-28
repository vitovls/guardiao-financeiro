---
type: TASKS
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Done
inv: INV007
branch: feat/llama-maverick-extracao-texto
---

# TASKS009 — Corrigir tipo/sinal, valor e gírias na extração de texto (troca para Llama 4 Maverick)

Diagnóstico em `docs/analysis/INV007-nova-lite-extracao-texto-tipo-valor-girias.md`. Resumo: `nova-lite` erra sinal/tipo (entrada↔saída), valor implícito (fica `0.00` silencioso) e conversão de gíria monetária ("conto") na extração de texto (`build_text_extraction_prompt` + `TEXT_MODEL_ID`), 6 casos documentados em `CONTEXT004`/`INV007`. Não há SPEC/PLN — rota curta, decisões já fechadas com o usuário durante o `/map-task` (ver "Decisão de Design" abaixo).

**Pré-requisito: `feat/nova-lite-extracao-documento` (`TASKS008`) precisa estar mergeada em `main` antes de começar esta task.** A branch desta TASKS é criada a partir de `main` **depois** desse merge — mesmo padrão de pré-requisito usado entre `TASKS007`→`TASKS008`.

**Branch:** `feat/llama-maverick-extracao-texto`, criada a partir de `main` pós-merge do `TASKS008`, nunca direto na `main`.

## Progresso

- [x] T1
- [x] T2
- [x] T3
- [x] T4 (portão de teste manual)

## Decisão de Design

Referência: `INV007`, seção "Decisões de Produto Confirmadas". Resumo:

1. `TEXT_MODEL_ID` migra de `"us.amazon.nova-lite-v1:0"` para `"us.meta.llama4-maverick-17b-instruct-v1:0"` (mesmo valor de `DOCUMENT_MODEL_ID`, já validado em `TASKS008`). **Sem mudança de IAM** — a policy já contém as 4 entradas de ARN necessárias (`scripts/aws/iam-policy-guardiao-dev.json`, aplicadas em `TASKS008` T7).
2. `TEXT_MODEL_ID` e `DOCUMENT_MODEL_ID` continuam sendo duas constantes independentes (mesmo padrão já usado no arquivo), mesmo tendo o mesmo valor agora — permite que voltem a divergir no futuro sem acoplamento, não é uma "segunda implementação" a fundir.
3. `build_text_extraction_prompt` ganha três instruções novas, todas explícitas (nenhuma inferência livre do modelo): convenção de sinal/tipo por direção do dinheiro, conversão de "conto" (1 conto = R$1) e tratamento de valor ausente (preencher `0.0`, não descartar a transação).
4. `services/message_service.py::format_message` ganha uma nota inline quando `valor == 0.0`, no mesmo padrão já usado para `categoria == DEFAULT_CATEGORIA` (linha 51-52 hoje).
5. Sem reprodução controlada prévia em `nova-lite` — os 6 casos do `CONTEXT004`/`INV007` são o baseline; o portão de teste manual (T4) roda esses mesmos 6 casos uma vez contra o modelo novo (A/B direto, não múltiplas rodadas).
6. Generalização: esta troca fixa Llama 4 Maverick como modelo padrão de extração via LLM no projeto (texto e documento), não uma decisão isolada — broadcast em `docs/PATTERNS.md` (T2 e T3 abaixo).

## T1 — Prompt: sinal/tipo, gíria "conto" e valor ausente

**Arquivo:** `prompts.py`

**Antes** (linhas 6-14):
```python
def build_text_extraction_prompt(today: str, text: str) -> str:
    return (
        f'A data de hoje é {today}. O usuário escreveu: "{text}". '
        f'Responda APENAS com JSON neste formato: {{"e_transacao": true|false, "transacoes": {TRANSACTION_SCHEMA}}}. '
        'Marque "e_transacao" como false se a mensagem não descrever um gasto ou '
        'recebimento (ex: saudação, pergunta, conversa solta). Nesse caso, '
        '"transacoes" deve ser uma lista vazia. '
        "Se não houver data explícita na mensagem, use a data de hoje."
    )
```

**Depois:**
```python
def build_text_extraction_prompt(today: str, text: str) -> str:
    return (
        f'A data de hoje é {today}. O usuário escreveu: "{text}". '
        f'Responda APENAS com JSON neste formato: {{"e_transacao": true|false, "transacoes": {TRANSACTION_SCHEMA}}}. '
        'Marque "e_transacao" como false se a mensagem não descrever um gasto ou '
        'recebimento (ex: saudação, pergunta, conversa solta). Nesse caso, '
        '"transacoes" deve ser uma lista vazia. '
        "Se não houver data explícita na mensagem, use a data de hoje. "
        'Determine "tipo" pela direção do dinheiro em relação ao usuário, nunca pela '
        'palavra isolada: dinheiro chegando ou recebido (salário que "caiu", Pix '
        'recebido, estorno a favor do usuário) é "entrada"; dinheiro gasto, pago ou '
        'a pagar (compra, boleto que "venceu" e ainda não foi pago) é "saida" — um '
        'boleto vencido é uma saída a pagar, nunca uma entrada, mesmo que a frase '
        'não pareça um gasto à primeira vista. '
        '"Conto" é gíria brasileira para R$1 — converta multiplicando o número '
        'informado por 1 (ex.: "10 conto" equivale a R$10,00), nunca por 100 ou 1000. '
        'Se a mensagem claramente descrever uma transação mas não mencionar um '
        'valor numérico explícito, ainda marque "e_transacao" como true e inclua a '
        'transação com "valor": 0.0 — não a descarte só por falta de valor.'
    )
```

`build_document_extraction_prompt` não é tocado.

**Teste** (`tests/test_prompts.py`, mudança de conteúdo de string, sem TDD estrito — mesmo tratamento de `T3`/`T3b` do `TASKS008`):
- `test_build_text_extraction_prompt_contains_date_text_and_flag` (já existe): continua verde, nenhuma asserção quebra.
- Novo `test_build_text_extraction_prompt_instructs_sign_convention`: `prompt = build_text_extraction_prompt(...)`; `assert "boleto" in prompt` (a palavra "boleto" só aparece na frase nova, diferente de "entrada"/"saida", que já existem em `TRANSACTION_SCHEMA` interpolado no prompt e por isso não discriminam a mudança).
- Novo `test_build_text_extraction_prompt_instructs_conto_conversion`: `assert "conto" in prompt` e `assert "R$1" in prompt` (garante que a conversão 1:1 está documentada, não só a palavra "conto").
- Novo `test_build_text_extraction_prompt_instructs_valor_ausente`: `assert "não a descarte" in prompt` (texto exclusivo da frase nova — **não** usar `'"valor": 0.0' in prompt` como asserção: essa substring já existe em `TRANSACTION_SCHEMA`, interpolado no prompt independente desta mudança, e passaria mesmo sem a instrução nova).

**Critério de aceitação:** `pytest tests/test_prompts.py` 100% verde.

## T2 — Trocar `TEXT_MODEL_ID` para Llama 4 Maverick

**Arquivo:** `services/llm/bedrock_provider.py` (linha 15):

**Antes:**
```python
TEXT_MODEL_ID = "us.amazon.nova-lite-v1:0"
```

**Depois:**
```python
TEXT_MODEL_ID = "us.meta.llama4-maverick-17b-instruct-v1:0"
```

`DOCUMENT_MODEL_ID` (linha 16) não é tocado — continua `"us.meta.llama4-maverick-17b-instruct-v1:0"`, já definido em `TASKS008`. As duas constantes ficam com o mesmo valor por coincidência de decisão, não por fusão de código — ver "Decisão de Design" item 2.

**IAM:** nenhuma mudança necessária. `scripts/aws/iam-policy-guardiao-dev.json` já contém as 4 entradas de `meta.llama4-maverick-17b-instruct-v1:0` (2 no `Statement` de inference profile, 3 regiões no de foundation model), aplicadas e confirmadas em `TASKS008` T7. Confirmar antes de prosseguir (não deveria ser necessário rodar nenhum comando `aws iam`):
```bash
grep -c "llama4-maverick" scripts/aws/iam-policy-guardiao-dev.json
```
Se o resultado for `< 4`, pare e trate como um achado novo (a policy divergiu do que este TASKS assume) antes de continuar — não há passo de IAM planejado aqui para corrigir isso.

**Teste:** nenhum teste novo necessário — `tests/services/llm/test_bedrock_provider.py` já importa `TEXT_MODEL_ID` do módulo e usa a constante em `call_kwargs["modelId"] == TEXT_MODEL_ID` (ex.: `test_extract_text_transactions_returns_transacoes_and_calls_converse_correctly`), acompanha automaticamente. `test_extract_text_transactions_does_not_set_temperature` continua válido e não muda — esta TASKS não altera `temperature` no fluxo de texto.

**Critério de aceitação:** `pytest` continua 100% verde.

**Broadcast em `docs/PATTERNS.md`** — adicionar como novo parágrafo dentro da entrada existente "Fallback de modelo por robustez segue a mesma família Nova antes de trocar de provedor" (depois do "Adendo (v1.2.0 do TASKS008)" já existente, ~linha 103):
```markdown
**Adendo (TASKS009):** `TEXT_MODEL_ID` também migrou de `nova-lite` para `meta.llama4-maverick-17b-instruct-v1:0`, generalizando a decisão para toda extração via LLM do projeto (texto e documento) — deixou de ser uma escolha isolada por fluxo. A decisão de pular o próximo tier Nova (`nova-pro`) antes de tentar foi deliberada: o modelo já estava validado no projeto para extração financeira semanticamente exigente, e o objetivo explícito era evitar reabrir um ciclo de ajuste de prompt já testado como caro em `TASKS008` (T3/T3b, duas iterações sem sucesso). Qualquer novo ponto de extração via LLM no projeto deve considerar `meta.llama4-maverick-17b-instruct-v1:0` como candidato padrão, não repetir a progressão nova-micro→nova-lite→nova-pro do zero. Origem: `docs/analysis/INV007-nova-lite-extracao-texto-tipo-valor-girias.md` / `docs/tasks/TASKS009-llama-maverick-extracao-texto.md`.
```

**Critério de aceitação:** parágrafo adicionado dentro da entrada existente, sem alterar nenhuma outra seção do arquivo.

## T3 — Alerta inline para valor ausente (`message_service.py`)

**Arquivo:** `services/message_service.py`

**Antes** (linhas 48-53):
```python
        notes = []
        if r.status == "suspeita":
            notes.append("parece semelhante a uma já registrada")
        if t.categoria == DEFAULT_CATEGORIA:
            notes.append(f'categoria não identificada, salva como "{DEFAULT_CATEGORIA}"')
        note = f" ({'; '.join(notes)})" if notes else ""
```

**Depois:**
```python
        notes = []
        if r.status == "suspeita":
            notes.append("parece semelhante a uma já registrada")
        if t.categoria == DEFAULT_CATEGORIA:
            notes.append(f'categoria não identificada, salva como "{DEFAULT_CATEGORIA}"')
        if t.valor == 0.0:
            notes.append("valor não identificado, revise")
        note = f" ({'; '.join(notes)})" if notes else ""
```

**Teste** (`tests/services/test_message_service.py`, TDD, seguindo `superpowers:test-driven-development` — mesmo padrão dos testes de `categoria` já existentes no arquivo):
- `test_format_message_valor_zero_shows_alert_note`: `_transacao(valor=0.0)`, status `"nova"` → `assert "valor não identificado" in message`.
- `test_format_message_valor_diferente_de_zero_does_not_show_alert_note`: `_transacao(valor=8.0)` (default já usado no arquivo) → `assert "valor não identificado" not in message`.
- `test_format_message_categoria_outros_e_valor_zero_combina_as_duas_notas`: `_transacao(categoria=DEFAULT_CATEGORIA, valor=0.0)` → `assert "categoria não identificada" in message and "valor não identificado" in message` (mesmo padrão do teste de combinação já existente para `suspeita` + `categoria`).

**Critério de aceitação:** os 3 testes novos passam; suíte completa de `test_message_service.py` continua verde.

**Broadcast em `docs/PATTERNS.md`** — duas entradas novas na seção "Decisões Estabelecidas", logo após a entrada existente "`Transacao.categoria` nunca fica vazia..." (~linha 107):
```markdown
### Gírias monetárias precisam de conversão explícita no prompt, nunca inferência livre do modelo

Gírias como "conto" não são universais no português do Brasil (podem significar R$1 ou, menos comumente, R$1000, a depender de região/época) — sem instrução explícita, o modelo aplicou uma conversão arbitrária (~×100, observada em `CONTEXT004`). Convenção adotada no projeto: 1 conto = R$1, documentada literalmente em `build_text_extraction_prompt` (`prompts.py`). Qualquer gíria monetária nova que o produto queira suportar precisa do mesmo tratamento — regra explícita no prompt, não confiança na interpretação do modelo. Origem: `docs/analysis/INV007-nova-lite-extracao-texto-tipo-valor-girias.md` / `docs/tasks/TASKS009-llama-maverick-extracao-texto.md`.

### `Transacao.valor` ausente/implícito segue o mesmo princípio de alerta inline de `categoria` vazia

Quando o texto do usuário claramente descreve uma transação mas não menciona um valor numérico explícito (ex.: "Gastei com mercado"), o prompt instrui o modelo a preencher `valor: 0.0` em vez de descartar a transação (`e_transacao: false`), e `services/message_service.py::format_message` avisa o usuário inline ("valor não identificado, revise") — mesmo padrão já usado para `categoria == DEFAULT_CATEGORIA`, sem fluxo de pergunta-e-espera-resposta (mesmo princípio "sem estado" de `SPEC006`). Qualquer novo campo que possa ficar ambíguo/ausente na extração via LLM deve seguir esse mesmo princípio: preencher um valor sentinela + alertar inline, não falhar silenciosamente nem bloquear o fluxo esperando confirmação. Origem: `docs/analysis/INV007-nova-lite-extracao-texto-tipo-valor-girias.md` / `docs/tasks/TASKS009-llama-maverick-extracao-texto.md`.
```

**Critério de aceitação:** as duas entradas adicionadas, sem alterar nenhuma outra seção do arquivo.

## T4 — Portão de teste manual (os 6 casos do `CONTEXT004`/`INV007`)

Com `LLM_PROVIDER=bedrock` real, rodar os mesmos 6 casos da tabela do `INV007` contra `extract_text_transactions` (já com T1+T2+T3 aplicados), uma vez cada (sem repetição — decisão de design item 5).

**Script novo** (`scripts/manual_test_text_extraction_cases.py`, mesmo padrão de `scripts/manual_test_document_extraction_variance.py`):
```python
import asyncio

from services.nlp_service import extract_text_transactions

_CASOS = [
    "Meu salario caiu de 3700 reais",
    "Salario caiu 3700 reais",
    "Gastei com mercado",
    "Pix de 10 conto caiu aqui",
    "Boleto de 150 venceu hoje",
    "Estornou 40 conto que cobraram errado oh",
]


async def main() -> None:
    for texto in _CASOS:
        transacoes = await extract_text_transactions(texto)
        print(f"\n=== {texto!r} ===")
        if not transacoes:
            print("  (nenhuma transação — e_transacao: false)")
            continue
        for t in transacoes:
            print(f"  {t.tipo} | R$ {t.valor:.2f} | {t.descricao!r}")


if __name__ == "__main__":
    asyncio.run(main())
```

**Critério de aceitação (por caso, comparar contra a coluna "Resultado esperado" do `INV007`):**

| Input | Esperado |
|---|---|
| `"Meu salario caiu de 3700 reais"` | reconhecida, `entrada`, R$3700,00 |
| `"Salario caiu 3700 reais"` | `entrada`, R$3700,00 |
| `"Gastei com mercado"` | reconhecida (não `e_transacao: false`), `saida`, R$0,00 (alerta de valor tratado em `T3`, fora do escopo do script) |
| `"Pix de 10 conto caiu aqui"` | `entrada`, R$10,00 |
| `"Boleto de 150 venceu hoje"` | `saida`, R$150,00 |
| `"Estornou 40 conto que cobraram errado oh"` | `entrada`, R$40,00 |

- **Se todos os 6 baterem:** ir para "Validação Final".
- **Se algum caso falhar:** documentar resultado observado vs. esperado por caso em uma nova seção do `INV007` ("Resultado da migração — T4"). Não inventar uma nova iteração de prompt aqui (mesma postura do `TASKS008` após T4b) — decidir com o usuário, via nova sessão de `/map-task`, se vale iterar o prompt, aceitar o resultado parcial (ainda estritamente melhor que a baseline de `nova-lite`), ou investigar outra causa. Esta TASKS não é reaberta especulativamente.

## Ordem de Execução

T1 → T2 → T3 → T4 (portão). T1-T3 são independentes entre si no código (arquivos diferentes) mas o portão T4 só faz sentido depois dos três aplicados juntos — não há execução condicional aqui (diferente do `TASKS008`, que tinha passos condicionais em cascata).

## Regra do Escoteiro / Testes

- TDD em T3 (vermelho antes do `if t.valor == 0.0`), seguindo `superpowers:test-driven-development`. T1 é mudança de conteúdo de string (mesmo tratamento não-TDD de `T3`/`T3b` do `TASKS008`). T2 é troca de constante, sem lógica nova.
- `pytest` deve passar 100% ao final de cada T de código, antes de avançar para o próximo T.
- Nenhum teste automatizado chama Bedrock real — T4 é o único ponto de chamada real, sempre manual, nunca automatizado (regra do `CLAUDE.md`).

## Cenários de Teste Manual

Coberto integralmente pelo portão T4 (não há cenário adicional além dos 6 casos da tabela).

## Fora de Escopo

- `extract_document_transactions`/`DOCUMENT_MODEL_ID` — já resolvido em `TASKS008`, não tocado aqui.
- Mudar o contrato de fingerprint/dedup (`repository/dedup.py`).
- Reprodução controlada com múltiplas rodadas em `nova-lite` antes da troca — decisão explícita do usuário de não investir nisso (`INV007`, "Decisões de Produto Confirmadas" item 2).
- Editar transação já salva / corrigir valor manualmente depois de registrada — feature separada (`CONTEXT003-editar-categoria-transacao.md`).
- Popular `.env`/documentação de custo de produção.
- Qualquer iteração adicional de prompt além da descrita em T1, caso T4 falhe — decisão a ser tomada com o usuário fora desta TASKS (ver T4, "Se algum caso falhar").

## Validação Final

- [x] T1: `build_text_extraction_prompt` com as 3 instruções novas (sinal/tipo, conto, valor ausente); `build_document_extraction_prompt` intocado; `pytest tests/test_prompts.py` verde.
- [x] T2: `TEXT_MODEL_ID` = `"us.meta.llama4-maverick-17b-instruct-v1:0"`; IAM confirmada sem necessidade de mudança (`grep -c "llama4-maverick" scripts/aws/iam-policy-guardiao-dev.json` = 4); broadcast em `PATTERNS.md` (adendo na entrada de fallback de modelo).
- [x] T3: alerta de valor ausente implementado e testado (TDD); broadcast em `PATTERNS.md` (2 entradas novas).
- [x] T4: os 6 casos do `CONTEXT004`/`INV007` rodados uma vez contra o modelo novo (`us.meta.llama4-maverick-17b-instruct-v1:0`, `LLM_PROVIDER=bedrock` real) — **os 6 bateram**:

  | Input | Esperado | Obtido |
  |---|---|---|
  | `"Meu salario caiu de 3700 reais"` | `entrada`, R$3700,00 | `entrada`, R$3700.00 ✅ |
  | `"Salario caiu 3700 reais"` | `entrada`, R$3700,00 | `entrada`, R$3700.00 ✅ |
  | `"Gastei com mercado"` | reconhecida, `saida`, R$0,00 | `saida`, R$0.00 ✅ |
  | `"Pix de 10 conto caiu aqui"` | `entrada`, R$10,00 | `entrada`, R$10.00 ✅ |
  | `"Boleto de 150 venceu hoje"` | `saida`, R$150,00 | `saida`, R$150.00 ✅ |
  | `"Estornou 40 conto que cobraram errado oh"` | `entrada`, R$40,00 | `entrada`, R$40.00 ✅ |

- [x] `pytest` 100% verde no ponto de parada final (111 passed).
- [x] Nenhuma mudança em `repository/dedup.py`, `extract_document_transactions`, `DOCUMENT_MODEL_ID` ou `build_document_extraction_prompt` (confirmado via `git diff --stat`).
