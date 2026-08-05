---
type: CONTEXT
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
origem: "Discussão de produto durante /map-task da Fase 6 (fluxo de consulta), docs/analysis/INV009-fluxo-consulta.md e docs/specs/SPEC011-fluxo-consulta.md"
---

# CONTEXT006 — Candidatos a fase futura levantados durante o fluxo de consulta (Fase 6)

Duas coisas ficaram de fora do escopo de `TASKS011-fluxo-consulta.md` de propósito — não são bugs nem pendências da Fase 6, são extensões conscientes que valem uma task própria mais adiante.

## 1. Padronização de categoria

### Contexto

`categoria` em `models.Transacao` é texto livre, decidido pela IA no momento de salvar (`prompts.py`), sem enum nem validação. Nada no sistema impede inconsistência — uma transação pode ser salva como `"mercado"` e outra semanticamente igual como `"alimentacao"`.

Isso virou visível ao desenhar o filtro de categoria da consulta (SPEC011 R6): a correspondência é textual exata após normalização (`repository.dedup.normalize_description`, trata acentos/case/pontuação), **sem sinônimos**. Uma pergunta como "quanto gastei em mercado?" só encontra transações salvas com a categoria `"mercado"`, não `"alimentacao"` — mesmo que o usuário pense nelas como a mesma coisa.

### Por que não foi feito junto

É uma mudança no lado de extração/salvamento (schema de `prompts.py`, comportamento da IA ao criar transação), ortogonal ao mecanismo de consulta da Fase 6. Mesmo travando uma taxonomia fixa hoje, os dados históricos já salvos livremente continuariam inconsistentes — exigiria também uma migração, não só uma mudança de prompt.

### Perguntas em aberto para quando isso virar task

- Taxonomia fixa (enum fechado) ou lista sugerida com opção de categoria nova? Taxonomia fechada é mais previsível para consulta, mas mais rígida para o usuário na hora de registrar.
- Categorias já salvas livremente precisam de migração/normalização retroativa, ou só transações novas seguem a regra nova (deixando o histórico como está)?
- Isso deveria abrir espaço para sinônimos na consulta (ex.: um mapa `"mercado"` → `"alimentacao"`) como alternativa/complemento a uma taxonomia fixa?

### Recomendação

Task própria via `/map-task` quando o uso real da consulta por categoria (Fase 6, já em produção) expuser o problema na prática — não há necessidade de adivinhar a taxonomia certa sem esse dado.

## 2. Consulta por listagem/ranking de transações individuais

### Contexto

A Fase 6 (`SPEC011`) só responde com **totais agregados** (entradas/saídas/saldo, ou o total de uma categoria) — nunca uma lista de transações. Perguntas como "me mostra minhas compras de julho" ou "qual foi minha maior compra?" ficam fora do escopo.

Isso **não é uma restrição arquitetural** — o invariante do projeto é "function calling + agregação, não RAG" (`docs/analysis/conversas-claude-ao-longo-do-tempo.md`), e RAG é busca semântica sobre texto não-estruturado com o LLM narrando livremente a partir do que recuperou. Retornar uma lista de transações filtradas por período/categoria via `Query` estruturado é o **mesmo mecanismo** de function-calling que a agregação já usa, só que a "ferramenta" devolve registros em vez de uma soma. O próprio design histórico do projeto (seção 8 do mesmo documento, 23/07/2026) já previa uma ferramenta de "maiores gastos", que exige devolver transações individuais, não um total.

### Por que não foi feito junto

Manter o incremento da Fase 6 pequeno. Listagem exigiria, além do que já foi construído:
- Uma sub-intenção dentro de `consulta` (ex.: "somar" vs. "listar") — o schema de `InterpretacaoTexto` (`PLN011-fluxo-consulta.md`) precisaria de mais um campo.
- Paginação/limite de itens numa resposta do Telegram (mensagens longas já são cortadas por `services/message_service.py::split_message`, mas listar todas as transações de um período pode ser uma lista grande demais para fazer sentido numa única resposta).
- Um formato de lista novo em `message_service.py` (a formatação atual só sabe resumir totais).

### Perguntas em aberto para quando isso virar task

- A sub-intenção "listar" reaproveita o mesmo `InterpretacaoTexto` com um campo a mais, ou justifica um DTO de resposta de consulta separado (agregação vs. listagem podem ter formas de resposta muito diferentes)?
- Existe um limite razoável de itens antes de pedir para o usuário refinar o período (ex.: "esse período tem 40 transações, tente um recorte menor")?
- "Maiores gastos"/ranking precisa de ordenação e top-N — isso é extração de parâmetro pela IA (ex.: "top 5") ou um valor fixo do produto?

### Recomendação

Task própria via `/map-task` — extensão natural do mesmo mecanismo de consulta construído na Fase 6, não uma feature nova do zero. Não é urgente; a Fase 6 (totais) já cobre o caso de uso mais comum ("quanto eu gastei").
