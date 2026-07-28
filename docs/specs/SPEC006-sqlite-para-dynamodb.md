---
type: SPEC
version: 1.0.0
author: Victor Veloso
date: 2026-07-27
status: Draft
inv: docs/analysis/INV004-sqlite-para-dynamodb.md
fase: "Fase 3 — docs/analysis/plano-contexto.md"
---

# SPEC006 — Dados: SQLite → DynamoDB (+ modelagem de orçamento)

## Intenção

Dar ao `repository/` uma segunda implementação real (DynamoDB), preservando o comportamento hoje coberto por SQLite, e fechar a lacuna de modelagem identificada em `INV004`: nem dedup determinística nem configuração de orçamento por usuário existem em lugar nenhum do sistema. Esta fase entrega ambos como schema + CRUD básico — a lógica de conselho financeiro que consome essas configurações (Fase 6b) continua fora de escopo.

## Contexto

Ver `docs/analysis/INV004-sqlite-para-dynamodb.md` para o diagnóstico completo (código atual, achados, pesquisa de mercado). Resumo do que este SPEC precisa fechar, das Perguntas em Aberto do INV:

1. Regra de dedup determinística (chave de "mesma transação", janela de tempo/tolerância) — **resolvida**: bloqueia e pede confirmação ao usuário (decisão do usuário, ver seção B).
2. Formato exato da entidade de orçamento (baldes) e se a dívida/crédito ("Serasa") entra no mesmo desenho — **resolvida**: mesmo shape, ver seção "Unificação balde/dívida" abaixo.

A pergunta 3 do INV (migração de dados do Notion) já foi resolvida como N/A — fora de escopo, transações entram pelo fluxo normal de extração via LLM. A pergunta 4 (comportamento de `init_db()` sob `DB_BACKEND=dynamo`) é decisão técnica, fica para o PLN.

## Decisão confirmada: dívida reaproveita o mesmo desenho de balde

Investigado a pedido do usuário: dívida (o "Serasa" da lacuna original) e balde (orçamento por categoria) têm naturezas diferentes à primeira vista — balde é um teto que **reseta todo mês**; dívida é um total que **nunca reseta**, só diminui conforme pagamentos. Mas o *shape* do dado é o mesmo, mudando só o que o campo `periodo` significa. Confirmado por pesquisa de mercado: o YNAB (referência já usada no `INV004` para orçamento) modela dívida **na mesma estrutura de categoria/envelope** dos baldes normais, diferenciando só pelo "tipo de meta" (*target type*) associado à categoria — "Monthly Funding" (recorrente, o caso do balde) vs. "Pay Off Balance by Date" / "Have a Balance Of" (o caso da dívida, sem reset mensal). Fonte: [How to Use YNAB's Targets](https://www.ynab.com/blog/ynab-targets) — "For monthly debt payment targets specifically, the Debt Payment target works exactly like a monthly target" (a estrutura é a mesma categoria; muda o comportamento de meta).

Aplicado ao Guardião: **um único Item de configuração (`sortKey = "CONFIG#{nome_normalizado}"`)**, cujo campo `periodo` assume `"mensal"` (balde, reseta a cada mês, agregação de gasto é sobre o mês corrente) ou `"unico"` (dívida, nunca reseta, agregação de gasto/pagamento é sobre todo o histórico desde `createdAt`). Não há dois prefixos de `sortKey` diferentes para balde e dívida — um único prefixo `CONFIG#` já basta, com `periodo` fazendo a distinção semântica. Isso descarta a ideia (do primeiro rascunho deste SPEC, já revisado) de uma entidade separada com campos próprios `valorTotal`/`valorRestante` para dívida — nenhum campo extra é necessário: `teto` já representa "valor total da dívida" quando `periodo="unico"`, e o saldo (quanto falta pagar) continua sendo sempre derivado (`teto - gasto agregado`, mesma regra de C2), nunca armazenado.

## Requisitos (EARS)

### A. Abstração de backend de persistência

- A1. O sistema deve expor uma interface `TransactionRepository` (ABC) com os contratos `save_transactions`, `find_by_user` e `get_totals_by_period`, seguindo o mesmo padrão de `LLMProvider`/`StorageProvider` (`services/llm/provider.py`, `services/storage/provider.py`): implementações concretas injetáveis via construtor, erros de provider traduzidos para uma exceção própria (`RepositoryError` ou equivalente), nunca vazando exceção nativa do backend para as camadas acima.
- A2. Quando `DB_BACKEND=sqlite`, o sistema deve usar uma implementação que preserva o comportamento atual (SQLAlchemy + `aiosqlite`), sem regressão de comportamento observável.
- A3. Quando `DB_BACKEND=dynamo`, o sistema deve usar uma implementação baseada em boto3 (DynamoDB), operando sobre a tabela única já desenhada no template (`GuardiaoFinanceiro-Transacoes-${Environment}`, PK `userId`, SK `sortKey`, GSI `GSI-Categoria`).
- A4. Se `DB_BACKEND` tiver valor diferente de `sqlite` ou `dynamo`, o sistema deve levantar `ValueError` na inicialização (mesmo padrão de `LLM_PROVIDER`/`STORAGE_BACKEND`).
- A5. O sistema deve manter `save_transactions` inserindo em lote (sem `commit`/`PutItem` dentro de loop sequencial não-batchado quando o backend suportar batch nativo) — para SQLite, mantém `session.add()` + `commit()` único já existente; para DynamoDB, agrupa em `batch_writer` quando aplicável.

### B. Dedup determinística de 3 estados

- B1. Para cada transação a inserir, o sistema deve derivar uma **chave de conteúdo determinística** a partir de `telegram_user_id + data + valor + tipo + descrição normalizada` (normalização: minúsculas, sem acentos, espaços colapsados, sem pontuação).
- B2. O sistema deve usar essa chave de conteúdo como (ou como parte de) o `sortKey` do Item DynamoDB, no formato `{data ISO}#{fingerprint}`, onde `fingerprint` é um hash determinístico (ex.: SHA-256 truncado) de `valor + tipo + descrição normalizada`.
- B3. Quando uma transação nova tiver `sortKey` idêntico a um Item já existente para o mesmo `userId`, o sistema deve classificar como **DUPLICATA EXATA** via `PutItem` com `ConditionExpression: attribute_not_exists(sortKey)` — a falha da condição (`ConditionalCheckFailedException`) É o sinal de duplicata exata, sem necessidade de query prévia.
- B3a. **Decisão do usuário:** DUPLICATA EXATA nunca é descartada nem inserida silenciosamente — o sistema deve bloquear a inserção automática e informar o usuário que uma transação idêntica já existe, pedindo confirmação explícita antes de gravar mesmo assim (cobre inclusive o caso legítimo de duas compras idênticas no mesmo dia, ex. dois cafés de R$8 — nesse caso raro, o usuário confirma e o sistema precisa de um mecanismo para permitir a segunda escrita, ex. sufixo de sequência no `sortKey` só quando confirmado). O mecanismo exato de "forçar gravação após confirmação" é decisão de implementação — fica para o PLN; aqui só o comportamento observável (bloquear + perguntar) é requisito.
- B3b. **Sem tratamento especial para adjacência/posição no lote.** Discutido explicitamente: duas transações idênticas extraídas do mesmo upload (mesma mensagem/foto/PDF), mesmo quando separadas por uma transação diferente no meio (ex.: café R$8, bolo R$10, café R$8), **não** ganham nenhuma exceção — o fingerprint não usa posição/adjacência como sinal, só os campos da própria transação (B1). O comportamento é sempre o de B3a: bloqueia e pede confirmação, sem distinguir "provável erro de OCR" de "duas compras reais". Decisão deliberada do usuário para manter a regra simples e 100% determinística nesta fase; não introduzir lógica de adjacência sem pedido explícito futuro.
- B4. Quando uma transação nova não colidir no `sortKey`, mas existir, dentro de uma janela de **60 a 90 dias** (parametrizável, default 90) do mesmo `userId`, um Item com `valor` e `tipo` idênticos e `descrição normalizada` com similaridade ≥ 0.8 (razão de similaridade, ex. `difflib.SequenceMatcher.ratio()` — sem introduzir dependência nova), o sistema deve classificar como **SUSPEITA** e retornar a(s) transação(ões) candidata(s) para quem chamou (o service decide o que fazer — bloquear, perguntar ao usuário, ou logar; essa decisão de UX não é escopo deste SPEC, que só define a classificação).
- B5. Quando nenhuma das condições acima for satisfeita, o sistema deve classificar como **NOVA** e inserir normalmente.
- B6. O sistema deve implementar a busca de candidatos da SUSPEITA (B4) via `Query` no DynamoDB por `userId` + faixa de `sortKey` (a janela de data), comparando em memória — nunca via `Scan`.
- B7. Enquanto o backend for `sqlite`, o sistema deve implementar a mesma regra de classificação (B1-B6) usando `SELECT` equivalente (`WHERE telegram_user_id = ? AND data BETWEEN ? AND ?`) — o resultado da classificação deve ser idêntico entre os dois backends para os mesmos dados de entrada (garante paridade, testável).
- B8. O sistema não deve usar nenhuma chamada a LLM na classificação de dedup — 100% determinística (invariante já estabelecido, `contexto-conversas-claude.md`).

### C. Modelagem e CRUD básico de configuração (orçamento e dívida — desenho unificado)

- C1. O sistema deve modelar um único tipo de Item de "configuração" por `userId` com `sortKey = "CONFIG#{nome_normalizado}"`, contendo: `nome` (S), `teto` (N — valor alocado por período quando `periodo="mensal"`, ou valor total da dívida quando `periodo="unico"`), `periodo` (S, `"mensal"` ou `"unico"`), `rollover` (BOOL, só tem efeito quando `periodo="mensal"` — se sobra acumula para o próximo mês; ignorado/`false` quando `periodo="unico"`, já que dívida sempre acumula pagamento por natureza), `dataLimite` (S, ISO 8601, opcional — vencimento, mais relevante para `periodo="unico"`), `createdAt`/`updatedAt` (S, ISO 8601). Ver "Decisão confirmada" acima para a justificativa da unificação (baseada no *target type* do YNAB).
- C2. O sistema **não** deve persistir "saldo disponível"/"valor restante" como atributo armazenado — esse valor é sempre derivado (`teto - gasto agregado`, via `get_totals_by_period`/`GSI-Categoria`), evitando dado duplicado que pode dessincronizar. A janela de agregação depende de `periodo`: mês corrente quando `"mensal"`, todo o histórico desde `createdAt` quando `"unico"` — essa é uma regra de leitura, não de escrita, e fica documentada aqui para a Fase 6b não redecidir do zero.
- C3. O sistema deve expor operações básicas de leitura e escrita (get/put) para o Item de configuração (C1) no `repository/`, sem nenhuma lógica de cálculo, narrativa ou agente de conselho associada — isso é Fase 6b.
- C4. O sistema não deve expor nenhum fluxo de chat/handler para o usuário criar ou editar configuração nesta fase — população inicial dos dados de configuração é feita por script/comando administrativo direto (fora do fluxo conversacional), executado pelo próprio usuário/desenvolvedor.
- C5. Onde a Fase 6b vier a construir o fluxo conversacional de leitura/escrita de configuração, o sistema deve mostrar ao usuário o valor a ser gravado e obter aprovação explícita antes de persistir (invariante registrado em `contexto-conversas-claude.md`, item 9 — não é critério de aceitação desta fase, é herança documentada).

### D. Migração de dados existentes

- D1. O sistema deve fornecer um script one-shot que lê todas as transações de `guardiao.db` (SQLite) e as insere na tabela DynamoDB, aplicando a mesma derivação de `sortKey` de B1-B2 (ou seja, dados históricos passam pela mesma regra de fingerprint).
- D2. O script deve reportar contagem de linhas lidas do SQLite vs. Items gravados no DynamoDB ao final, para conferência manual.
- D3. O script não deve apagar ou modificar `guardiao.db` — o arquivo continua como backup até estabilidade confirmada em produção.
- D4. Não há dado de configuração (orçamento/dívida) para migrar automaticamente — nenhuma linha do SQLite hoje representa esse tipo de dado (ver Non-Goals).

### E. Consulta de totais (portado da branch não mesclada)

- E1. O sistema deve expor `get_totals_by_period(telegram_user_id, start, end) -> dict[str, float]` em ambos os backends (`sqlite`, `dynamo`), com o mesmo contrato e mesmo resultado que a implementação já existente em `feature/nlp-query-totals` (agregação de `entradas`/`saidas` por período).
- E2. Para `dynamo`, o sistema deve implementar E1 via `Query` por `userId` + faixa de `sortKey` (mesma janela de data usada pela busca de SUSPEITA, reaproveitando o padrão de acesso), agregando em memória — sem `Scan`.

## Non-Goals (fora de escopo desta fase)

- Lógica do agente de conselho (Fase 6b): cálculo de "posso gastar X", narrativa sobre orçamento, qualquer chamada a LLM sobre dados de configuração.
- Fluxo de chat/handler para o usuário criar, editar ou consultar configuração (baldes/dívida) — só CRUD de baixo nível no `repository/`.
- Importador de transações do Notion — fora de escopo por decisão do usuário (INV004), transações entram pelo fluxo normal de extração via LLM.
- Remoção do `SqliteTransactionRepository`/fallback `DB_BACKEND=sqlite` — permanece até estabilidade confirmada em produção com `dynamo` (mesmo ciclo de vida de `GeminiProvider`/`LocalStorageProvider`).
- Webhook, Step Functions, decomposição em Lambda — fases 4 e 5.
- Fuzzy-matching avançado (embeddings, NLP) para a comparação de descrição em B4 — usa `difflib` da stdlib, nada além disso.
- Criação da tabela DynamoDB via código — provisionamento é ação manual do usuário via AWS CLI (`PATTERNS.md`).

## Critérios de Aceitação

1. Duas transações idênticas (`userId`, `data`, `valor`, `tipo`, `descrição` iguais) inseridas em sequência: a segunda **não** é inserida nem descartada automaticamente — o sistema bloqueia, classifica como DUPLICATA EXATA e sinaliza que precisa de confirmação do usuário antes de gravar (B3a), sem exigir `Query` prévia (só a condição do `PutItem` falha).
2. Duas transações com `valor` e `tipo` iguais, `descrição` levemente diferente (ex. ruído de OCR), datas dentro de 90 dias uma da outra: classificadas como SUSPEITA, ambas retornadas como candidatas — nenhuma é bloqueada automaticamente (SUSPEITA não é DUPLICATA EXATA).
3. Duas transações reais e distintas no mesmo dia, mesmo valor, mesma descrição normalizada (ex. dois cafés de R$8): por decisão do usuário, esse caso **também** é tratado como DUPLICATA EXATA por B1-B3 — o sistema bloqueia e pede confirmação (B3a) em vez de inserir/descartar silenciosamente. Não há tratamento especial para repetição legítima no mesmo dia; o custo é uma confirmação manual ocasional, aceito como caso raro.
4. Transação sem nenhum candidato em 90 dias: classificada como NOVA, inserida normalmente.
5. `get_totals_by_period` retorna o mesmo resultado nos dois backends (`sqlite` vs. `dynamo`) para o mesmo conjunto de dados de teste.
6. Um Item de configuração criado via CRUD básico com `teto=500`, `periodo="mensal"` permite calcular gasto restante combinando `teto` com o agregado de `get_totals_by_period` filtrado por categoria (mês corrente) — sem nenhum atributo de saldo persistido no Item.
7. Um Item de configuração criado com `teto=3000`, `periodo="unico"` (dívida) permite calcular saldo restante combinando `teto` com o agregado de `get_totals_by_period` desde `createdAt` (todo o histórico) — mesmo mecanismo de C1/C2, sem campos extras de dívida.
8. Script de migração roda contra uma cópia de `guardiao.db` com N transações e reporta N linhas lidas / N Items gravados (sem perda), sem alterar o arquivo `.db` original.
9. `DB_BACKEND` com valor inválido levanta `ValueError` na inicialização, mesmo comportamento de `LLM_PROVIDER`/`STORAGE_BACKEND`.
