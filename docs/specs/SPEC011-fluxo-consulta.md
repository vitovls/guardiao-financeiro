---
tipo: SPEC
numero: SPEC011
slug: fluxo-consulta
inv: INV009
status: Draft
---

# SPEC011 — Fluxo de consulta (Fase 6)

## Intenção

Permitir que o usuário pergunte, em linguagem natural, por totais financeiros de um período (e opcionalmente de uma categoria) — "quanto gastei esse mês?", "quanto entrou em junho?", "quanto gastei em mercado em julho?" — e receba uma resposta agregada, sem precisar de um comando dedicado. Fecha a Fase 6 do `docs/analysis/plano-contexto.md`: classificação de intenção (transação × consulta × nenhuma) na mesma chamada de IA que já extrai transação, e resposta via agregação determinística sobre o DynamoDB/SQLite já existentes — nunca RAG.

## Contexto

Ver `docs/analysis/INV009-fluxo-consulta.md` para o levantamento completo. Resumo do estado atual relevante:

- A camada de dados (`get_totals_by_period`) já existe e está testada nos dois repositories, mas não filtra por categoria e não é chamada por nenhum handler.
- `LLMProvider.extract_text_transactions` só distingue "é transação" (`true`/`false`) — não existe "consulta" como intenção.
- Nenhum roteamento por intenção existe em `handlers/text_handler.py`; toda mensagem de texto é tratada como candidata a transação.
- Decisões de produto já confirmadas pelo usuário (herdadas do INV009, não reabertas aqui):
  1. Classificação de intenção + extração de filtros de consulta acontece na mesma chamada de IA que hoje extrai transação (schema estendido, sem chamada extra ao Bedrock). `GeminiProvider` também implementa a nova assinatura.
  2. Filtro por categoria é aplicado em memória sobre o resultado já trazido do período — sem Query nova no `GSI-Categoria`.
  3. Consulta com categoria responde só com o total daquela categoria, não o resumo completo de entradas/saídas/saldo.

## Requisitos (EARS)

**Classificação de intenção**

- R1: Quando o usuário envia uma mensagem de texto, o sistema deve classificá-la em exatamente uma de três intenções: `transacao`, `consulta` ou `nenhuma`, na mesma chamada de IA que hoje extrai transações.
- R2: Quando a intenção classificada for `transacao`, o sistema deve seguir o fluxo já existente (extração, dedup, salvamento, confirmação) sem nenhuma mudança de comportamento observável.
- R3: Quando a intenção classificada for `nenhuma`, o sistema deve responder informando que não identificou nem uma transação nem uma consulta, com um exemplo de cada (ex.: "Gastei 30 reais no mercado" e "Quanto gastei esse mês?").

**Extração de filtros de consulta**

- R4: Quando a intenção classificada for `consulta`, o sistema deve tentar extrair um período (data de início e data de fim) e, opcionalmente, uma categoria, a partir do texto da mensagem, na mesma chamada de IA.
- R5: Quando a intenção for `consulta` e a IA não conseguir identificar um período explícito ou implícito na mensagem, o sistema deve responder pedindo para o usuário especificar o período (ex.: "Qual período você quer consultar? Ex: 'esse mês', 'junho', 'este ano'."), sem assumir um período padrão.
- R6: Quando a mensagem de consulta mencionar uma categoria, o sistema deve normalizar o texto da categoria extraída (minúsculas, sem espaços nas pontas) antes de comparar com as categorias salvas — correspondência é textual exata após normalização, sem sinônimos (ex.: "mercado" só combina com uma transação salva com categoria "mercado", não com "alimentacao"). Essa limitação é conhecida e aceita nesta fase.

**Agregação e resposta**

- R7: Quando a intenção for `consulta` sem categoria, o sistema deve responder com o total de entradas, total de saídas e saldo do período identificado, reaproveitando `get_totals_by_period` sem modificação de comportamento.
- R8: Quando a intenção for `consulta` com categoria, o sistema deve responder apenas com o total gasto/recebido naquela categoria no período — sem entradas/saídas/saldo geral.
- R9: Quando a consulta (com ou sem categoria) não encontrar nenhuma transação no período pedido, o sistema deve responder de forma explícita informando que não houve transações nesse período/categoria, nunca mostrar silenciosamente "R$ 0,00" sem contexto.
- R10: A resposta de consulta deve seguir o mesmo padrão visual já usado em `format_message` (emoji, formatação de moeda `R$ X.XX`, rótulo de período em português) para manter consistência de produto.

**Compatibilidade e não regressão**

- R11: Nenhuma mudança desta fase deve alterar o fluxo de foto/PDF (`handlers/photo_handler.py`, `handlers/pdf_handler.py`, `services/ocr_service.py`) — consulta é exclusiva de mensagens de texto.
- R12: Nenhuma mudança desta fase deve alterar o comportamento de dedup, confirmação de pendência ou salvamento de transação quando a intenção for `transacao`.

## Non-Goals

- Consulta por listagem de transações individuais (ex.: "me mostra minhas compras de julho") — nesta fase, só totais agregados, nunca uma lista. **Importante:** isso é um corte de escopo do incremento, não uma proibição arquitetural — listar transações via `Query` estruturado não é RAG (RAG seria busca semântica sobre texto não-estruturado com o LLM narrando livremente; retornar registros filtrados por período/categoria é o mesmo mecanismo de function-calling que a agregação usa, só que a "ferramenta" devolve linhas em vez de uma soma). O design histórico do projeto (`docs/analysis/conversas-claude-ao-longo-do-tempo.md`, seção 8) já previa uma ferramenta de "maiores gastos", que exige devolver transações individuais — ver "Candidatos a Fase Futura" abaixo.
- Sinônimos ou correspondência aproximada de categoria (ex.: "mercado" ≈ "alimentacao") — fica para uma fase futura, se necessário. Ver "Candidatos a Fase Futura" abaixo.
- Uso do `GSI-Categoria` da tabela DynamoDB — decisão já tomada de filtrar em memória (INV009, decisão 2).
- Período padrão implícito quando a IA não identifica um período — sempre pergunta ao usuário (R5).
- Qualquer alteração em `GeminiProvider`/`BedrockProvider` além do necessário para o novo contrato de classificação+extração (não é objetivo desta fase ajustar o schema de extração de transação em si).
- Fase 6b ("conselhos financeiros") — mecanismo de consulta construído aqui deve ser reutilizável por ela no futuro, mas implementá-la está fora de escopo.
- Remoção de `GeminiProvider`/`GEMINI_API_KEY` — tarefa "(pós-estabilidade)" da Fase 1, não relacionada a esta fase.
- Consultas por texto livre sem categoria/período reconhecíveis mas com outras dimensões (ex.: "qual foi minha maior compra?") — fora de escopo nesta fase, cobre só total por período/categoria. Mesma observação do primeiro item: não é RAG que está sendo evitado aqui, é escopo de incremento (ver "Candidatos a Fase Futura").

## Candidatos a Fase Futura

Registrado nesta sessão, fora do escopo de implementação do TASKS011 — não bloqueiam esta fase, mas não devem ser esquecidos:

- **Padronização de categoria.** Hoje `categoria` é texto livre decidido pela IA no momento de salvar (sem enum, sem validação) — nada no sistema impede inconsistência (`"mercado"` numa transação, `"alimentacao"` noutra semanticamente igual). Isso é a causa raiz da limitação aceita em R6 (correspondência exata, sem sinônimos): mesmo com sinônimos implementados no futuro, o problema de fundo é a ausência de rigidez na criação da categoria. É uma mudança no lado de extração/salvamento (`prompts.py`, schema de transação), ortogonal ao mecanismo de consulta desta fase, e exigiria decidir uma taxonomia e migrar dados históricos já salvos livremente — candidato a um INV próprio (ex.: "padronizar categorias"), não a uma tarefa dentro desta.
- **Consulta por listagem/ranking de transações individuais** (ex.: "me mostra minhas compras de julho", "qual foi minha maior compra?"). Não é vetado pelo invariante "function calling + agregação, não RAG" do projeto — é o mesmo mecanismo de ferramenta estruturada, só que devolvendo registros em vez de uma soma, e já estava previsto no design histórico ("maiores gastos", `conversas-claude-ao-longo-do-tempo.md` seção 8). Fica fora desta fase para manter o incremento pequeno: exigiria decidir uma sub-intenção dentro de `consulta` ("somar" vs "listar"), paginação/limite de itens numa resposta do Telegram, e um formato de lista novo em `message_service.py`. Extensão natural do mesmo mecanismo construído aqui — candidato direto a uma Fase 6.1/6b.

## Critérios de Aceitação

1. Enviar "gastei 30 no mercado" continua salvando a transação exatamente como hoje (sem regressão).
2. Enviar "quanto gastei em julho de 2026?" responde com entradas, saídas e saldo de julho/2026, calculados a partir dos dados reais do usuário.
3. Enviar "quanto gastei em mercado em julho de 2026?" (supondo transações salvas com `categoria="mercado"`) responde só com o total gasto em "mercado" em julho/2026.
4. Enviar "quanto eu já gastei?" (sem período reconhecível) responde pedindo o período, sem consultar o banco.
5. Enviar uma consulta de período/categoria válida sem nenhuma transação correspondente responde de forma explícita que não houve transações, não "R$ 0,00" isolado.
6. Enviar "oi" (nem transação nem consulta) responde com a mensagem de fallback atualizada, mencionando os dois tipos de uso possíveis.
7. `GeminiProvider` e `BedrockProvider` implementam o novo contrato de forma equivalente (mesma interface, mesmo shape de retorno) — testado com providers mockados, sem chamada real a LLM.
8. Suíte de testes automatizados cobre: as 3 intenções, extração de período (presente/ausente), extração de categoria (presente/ausente), resposta com e sem categoria, resposta de zero resultados — sem nenhuma chamada real a LLM/AWS (mesmo padrão de `docs/PATTERNS.md`).
9. `pytest` passa 100% incluindo os testes já existentes (não regressão).
