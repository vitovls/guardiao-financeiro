# Design: Sistema de Consultas NLP — Totais por Período

**Data:** 2026-06-28  
**Escopo:** Primeiro passo do sistema de consultas — responder entradas totais, saídas totais e saldo para um período especificado pelo usuário em linguagem natural.

---

## Contexto

O bot atualmente só grava transações. Qualquer mensagem que não seja transação recebe "Não foi identificada nenhuma transação". Este design adiciona um segundo caminho: consultas, com foco inicial em totais por período.

Auth (`auth_service.is_user_authorized`) está inativo — qualquer usuário do Telegram pode usar o bot. Isso é pré-existente e será tratado em task separada.

---

## Arquitetura

### Novos arquivos

| Arquivo | Responsabilidade |
|---|---|
| `services/intent_service.py` | Call 1 ao Gemini: classifica intent da mensagem |
| `services/query_service.py` | Call 2b ao Gemini: extrai período + monta resposta |

### Arquivos modificados

| Arquivo | O que muda |
|---|---|
| `handlers/text_handler.py` | Adiciona roteamento por intent (3 caminhos) |
| `repository/transaction.py` | Adiciona `get_totals_by_period()` |
| `services/transaction_service.py` | Adiciona `get_totals()` |

### Arquivos intocados

`nlp_service.py`, `ocr_service.py`, `message_service.py`, `models.py`, `prompts.py`, `photo_handler.py`, `pdf_handler.py`.

---

## Fluxo de dados

```
text_handler
  └─ intent_service.classify(text)              ← Call 1 Gemini
       ├─ "transaction" → nlp_service.extract() ← Call 2a (existente, inalterado)
       │    └─ save_transactions() → DB
       ├─ "query"       → query_service.resolve_query(text, user_id)
       │    ├─ Call 2b Gemini: extrai período → {"inicio": date, "fim": date}
       │    ├─ transaction_service.get_totals(user_id, start, end) → DB
       │    └─ formata e retorna resposta
       └─ "unknown" → resposta de ajuda (sem nova chamada ao Gemini)
```

---

## Chamadas ao Gemini

### Call 1 — `intent_service.classify(text)`

Prompt minimalista. Retorno:

```json
{"intent": "transaction" | "query" | "unknown"}
```

Exemplos de classificação:
- `"gastei 50 no mercado"` → `transaction`
- `"quanto gastei esse mês?"` → `query`
- `"oi tudo bem?"` → `unknown`

### Call 2b — `query_service` (extração de período)

Recebe a data de hoje (igual ao `nlp_service`) para resolver expressões relativas. Retorno:

```json
{
  "periodo_identificado": true,
  "inicio": "2026-06-01",
  "fim": "2026-06-30"
}
```

Se o período não for identificável: `{"periodo_identificado": false}` — nenhuma query ao banco é feita.

---

## Agregação no repositório

```python
async def get_totals_by_period(
    self, telegram_user_id: int, start: date, end: date
) -> dict[str, float]:
    # Retorna {"entradas": float, "saidas": float}
    # Duas queries: SUM(valor) WHERE tipo='entrada' e SUM(valor) WHERE tipo='saida'
    # filtradas por telegram_user_id e intervalo de datas
```

Exposto via `transaction_service.get_totals(user_id, start, end)`.

---

## Formato da resposta

```
📊 Resumo de junho/2026

Entradas:  R$ 3.200,00
Saídas:    R$ 1.847,50
Saldo:     R$ 1.352,50
```

---

## Casos de borda

| Situação | Comportamento |
|---|---|
| Nenhuma transação no período | Mostra `R$ 0,00` em tudo, sem erro |
| Período não identificado | "Qual período você quer consultar?" — sem query ao banco |
| Intent "unknown" | Mensagem de ajuda genérica, sem segunda chamada ao Gemini |

---

## O que NÃO está no escopo desta task

- Ativação do `auth_service` (task separada)
- Consultas por categoria
- Consultas com período padrão (ex: mês atual sem o usuário especificar)
- Qualquer mudança nos fluxos de foto e PDF
