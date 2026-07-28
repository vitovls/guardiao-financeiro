---
type: CONTEXT
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
origem: "Discussão de produto durante TASKS006-sqlite-para-dynamodb.md, após o fallback de categoria \"outros\""
---

# CONTEXT003 — Editar a categoria de uma transação já salva

## Contexto

`models.Transacao` agora garante que `categoria` nunca fica vazia — quando a IA não consegue identificar, cai em `DEFAULT_CATEGORIA = "outros"` (`models.py`), e `services/message_service.py::format_message` avisa o usuário inline na mesma mensagem ("categoria não identificada, salva como 'outros'").

O usuário pediu, na mesma conversa, um passo além: quando isso acontecer, poder **responder e corrigir** a categoria daquela transação específica. Ficou decidido explicitamente adiar essa parte — o fallback + alerta (sem edição) foi implementado; a edição de verdade fica para depois.

## Por que não foi feito junto

Não existe hoje, em lugar nenhum do sistema, nenhuma forma de:
- Referenciar de volta uma transação específica já salva (nenhum ID curto/legível é exposto ao usuário nas mensagens do bot).
- Atualizar (`update`) uma transação existente — nenhum repository (`SqliteTransactionRepository`, `DynamoTransactionRepository`) tem esse método, só `save_transactions`/`find_by_user`/`get_totals_by_period`.
- Nenhum handler trata resposta a uma mensagem anterior do bot (`reply_to_message`) nem qualquer outro mecanismo de correlacionar "essa mensagem do usuário corrige aquela transação ali".

Ou seja, é uma feature nova de verdade — precisa de decisão de design (como referenciar a transação: ID curto? responder à mensagem do bot via `reply_to_message`? comando `/categoria <id> <nova>`?), método de update nos dois repositories, e handler novo. Maior que um fallback, por isso ficou fora do escopo do TASKS006.

## Perguntas em aberto para quando isso virar task

- Como o usuário referencia a transação a corrigir? Opções: `reply_to_message_id` do Telegram (responder à mensagem específica do bot), um ID curto exposto na mensagem (ex: últimos caracteres do fingerprint), ou listar as N últimas "outros" e deixar escolher por número.
- `update` no repository precisa reescrever o Item inteiro (Dynamo) ou só o campo `categoria`? Se só a categoria mudar, o `sortKey` (que depende de `valor+tipo+descrição`) não muda — mais simples. Mas normalizar isso entre SQLite e DynamoDB precisa de desenho.
- Vale reaproveitar esse mesmo mecanismo de "responder pra corrigir" para outros campos no futuro (ex: corrigir valor errado de OCR), ou é específico de categoria?

## Recomendação

Tratar como task própria via `/map-task` quando o usuário quiser priorizar. Não é urgente — o fallback + alerta já cobre a garantia mínima pedida ("sempre deve existir uma categoria").
