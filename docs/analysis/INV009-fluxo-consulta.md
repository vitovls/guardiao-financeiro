---
tipo: INV
numero: INV009
slug: fluxo-consulta
status: Draft
---

# INV009 — Fluxo de consulta (Fase 6)

## Contexto

**Gatilho:** `/map-task fase 6 @docs/analysis/plano-contexto.md`. `docs/analysis/plano-contexto.md` (linhas 217-223 e 307-311) descreve a Fase 6 como a próxima fase da migração: classificar mensagem de texto como transação × consulta, extrair filtros estruturados (período, categoria) e responder com totais agregados — mantendo a decisão de produto já registrada no plano: **function calling + agregação, nunca RAG**.

**Branch:** `feat/fluxo-consulta` (já criada a partir de `feat/confirmacao-duplicata-exata`, contém só o commit de docs `1bdbb4b`, nenhum código ainda).

**Fases anteriores confirmadas em produção** (verificado no código, não só no plano): Bedrock (`services/llm/bedrock_provider.py`), S3 (`services/storage/s3_provider.py`), DynamoDB (`repository/dynamo_repository.py`). Fase 6 não depende de Fase 4/5 (arquivadas) — só da Fase 3, concluída.

**Trabalho de referência descartado:** existe um worktree/branch `feature/nlp-query-totals` (`.worktrees/feature/nlp-query-totals`) com uma tentativa anterior e **independente** desta migração (`services/intent_service.py`, `services/query_service.py`, ver histórico de commits `5229f9e`, `7f7b609`, `78f0147`). Não é uma tentativa parada da Fase 6 e não deve ser mergeada ou usada como base de código — foi escrita antes da migração para Bedrock/DynamoDB, chama `google.genai` **diretamente** dentro de `services/` (violando "IA apenas em `ocr_service.py`/`nlp_service.py`" de `docs/PATTERNS.md`) e opera sobre o schema SQLite antigo (`repository/transacao.py`, tabela `Transacao` sem dedup por fingerprint). Serve só como referência conceitual: o formato de prompt de extração de período (`services/query_service.py`, pergunta o período em linguagem natural e devolve `{"periodo_identificado": bool, "inicio", "fim"}`) e a mensagem de fallback quando o período não é identificável ("Qual período você quer consultar? Ex: 'esse mês', 'junho', 'este ano'.").

## Bloco 1 — Camada de dados: já pronta, não usada

**Descrição observada:** `TransactionRepository` (`repository/provider.py:40`) já declara `get_totals_by_period(telegram_user_id, start, end) -> dict[str, float]` (linhas 49-51), implementado em ambos os backends:
- `repository/sqlite_repository.py:92-108` — `GROUP BY TransactionEntity.tipo` com filtro de intervalo de `data`.
- `repository/dynamo_repository.py:273-294` — `Query` por `userId` + `sortKey` entre `{start}#` e `{end}#{_HIGH_SENTINEL}` (reaproveita o sentinela documentado em `PATTERNS.md`, seção "Query por faixa de data..."), soma `entradas`/`saidas` em memória, pulando itens especiais (`_ESPECIAIS = ("CONFIG#", "PENDENTE#", "PROCESSADO#")`).

`services/transaction_service.py:18-20` já expõe `get_totals(telegram_user_id, start, end)` chamando o repository. Testado (`tests/repository/test_sqlite_repository.py:61-99`, `tests/repository/test_dynamo_repository.py:167-179`, `tests/services/test_transaction_service.py:29-37`).

**Análise de causa raiz:** esse código foi construído durante a Fase 3 (`TASKS006-sqlite-para-dynamodb.md`) em antecipação à Fase 6, mas nunca foi chamado por um handler — não existe nenhum ponto de entrada (comando, roteamento de intenção) que invoque `get_totals`. É código morto até hoje.

**Arquivos relevantes:** `repository/provider.py:49-51`, `repository/sqlite_repository.py:92-108`, `repository/dynamo_repository.py:273-294`, `services/transaction_service.py:18-20`.

**O que falta:** filtro por **categoria** — `get_totals_by_period` não aceita categoria hoje, só período. A tabela real (`GuardiaoFinanceiro-Transacoes-dev`) tem `GSI-Categoria` **ativo** (confirmado em `docs/tasks/TASKS006-sqlite-para-dynamodb.md` linhas 914/923, `describe-table` retornou `GSI-Categoria` em `GlobalSecondaryIndexes`), mas nenhum código consulta esse índice ainda.

## Bloco 2 — Camada de IA: só extrai transação, não classifica intenção

**Descrição observada:** `LLMProvider` (`services/llm/provider.py:14-20`) declara só dois métodos: `extract_text_transactions(text) -> list[Transacao]` e `extract_document_transactions(file_bytes, mime_type) -> list[Transacao]`. `build_text_extraction_prompt` (`prompts.py:6-25`) já pede ao modelo um booleano de classificação (`"e_transacao": true|false`) mas só para decidir se a mensagem é transação ou não — não existe uma terceira categoria ("consulta"), nem extração de filtros de período/categoria.

Ambas as implementações (`services/llm/gemini_provider.py:16-40`, `services/llm/bedrock_provider.py:71-119`) fazem exatamente **uma** chamada ao provedor por mensagem de texto, parseiam o JSON e retornam `list[Transacao]` (vazio quando `e_transacao` é `false`). `handlers/text_handler.py:10-29` chama `extract_text_transactions` incondicionalmente; se a lista vier vazia, responde "Não foi identificada nenhuma transação nessa mensagem. Tente algo como 'Gastei 30 reais no mercado'" (linhas 17-21) — hoje esse é o único destino de qualquer mensagem de texto que não seja transação, inclusive uma consulta.

**Análise de causa raiz:** a Fase 1 (`TASKS004-gemini-para-bedrock.md`) e as fases seguintes de ajuste de prompt (`TASKS007`, `TASKS008`, `TASKS009`) desenharam o schema de extração só para o caso de uso "transação"; consulta não existia como conceito no produto até a Fase 6.

**Arquivos relevantes:** `services/llm/provider.py:14-20`, `prompts.py:6-25`, `services/llm/gemini_provider.py:16-40` (`extract_text_transactions`, linhas 19-28), `services/llm/bedrock_provider.py:81-84` (`extract_text_transactions`) e `95-97` (`_parse_text_response`), `services/nlp_service.py:9-14`, `handlers/text_handler.py:10-29`.

**Decisão de Produto Confirmada (usuário, nesta sessão):** a classificação de intenção (`transacao`/`consulta`/`nenhuma`) e a extração de filtros de consulta (período, categoria) acontecem na **mesma chamada** ao provedor que hoje já extrai transação — schema JSON estendido, sem chamada adicional ao Bedrock. Isso muda a assinatura do método correspondente em `LLMProvider`, portanto **`GeminiProvider` também precisa implementar** a nova versão (mantém a paridade exigida pelo padrão "troca de provedor externo" de `docs/PATTERNS.md`, já que `LLM_PROVIDER` ainda aceita `"gemini"` como valor válido — `run_polling/config.py:8`, default atual do código é `"gemini"`, embora a produção real rode com `bedrock` segundo `plano-contexto.md`). Alternativa descartada: duas chamadas separadas (classificar intenção primeiro, extrair filtros depois) — dobraria custo/latência de **toda** mensagem de texto, inclusive as que já são transação e hoje resolvem em uma chamada só.

## Bloco 3 — Roteamento e resposta: não existem

**Descrição observada:** não há nenhum código de roteamento por intenção. `handlers/text_handler.py` trata toda mensagem de texto como candidata a transação. `services/message_service.py` só tem formatadores para resultado de transação (`format_message:30-68`) e para pendência de confirmação (`format_pending_message:70-83`) — nenhum formatador de resposta de consulta.

**Análise de causa raiz:** consulta é feature nova; nada disso existia antes da Fase 6.

**O que já existe de parecido para seguir como referência:**
- Padrão de formatação de resposta com emoji + resumo estruturado: `format_message` (`services/message_service.py:30-68`).
- Padrão "roteamento simples dentro do handler, sem lógica de negócio": `handlers/pending_handler.py:24-35` decide com base em `query.data.split(":", 2)`.
- Padrão de serviço fino delegando ao repository: `services/transaction_service.py` inteiro.

**Decisões de Produto Confirmadas (usuário, nesta sessão):**
1. Quando a consulta menciona uma categoria (ex.: "quanto gastei em mercado"), o filtro é aplicado **em memória** sobre o resultado de `get_totals_by_period` (Query já existente pela chave primária) — não cria uma Query nova no `GSI-Categoria`. Motivo: volume baixo de um bot pessoal, mesmo raciocínio que justificou arquivar Fase 4/5 em `plano-contexto.md`.
2. Quando a consulta pede uma categoria específica, a resposta mostra **só o total daquela categoria** (ex.: "Você gastou R$ 320,00 em mercado em julho/2026"), não o resumo completo de entradas/saídas/saldo — que não faz sentido filtrado por uma única categoria de despesa.

## Relação entre os problemas

Os três blocos formam uma cadeia de dependência de baixo para cima: Bloco 1 (dados) já está pronto e só precisa aprender a filtrar por categoria em memória (decisão do usuário evita tocar o repository para isso — o filtro fica na camada de serviço/formatação, não no repository, então **o Bloco 1 pode ficar praticamente intocado**, exceto talvez expor `find_by_user`/dados brutos por categoria se `get_totals_by_period` não for suficiente — ver Pergunta em Aberto 3). Bloco 2 (IA) precisa mudar para alimentar o Bloco 3 (roteamento/resposta) com `intencao` + filtros. Bloco 3 é o que efetivamente não existe e amarra os outros dois.

## Observações de Runtime confirmadas pelo usuário

Nenhuma — não há comportamento em produção a observar (feature nova).

## Perguntas em Aberto

1. **Nome e forma do novo contrato de retorno** de `LLMProvider` para texto (novo método? mesmo nome com assinatura estendida? novo modelo Pydantic para o resultado, com `intencao`, `transacoes`, período, categoria?). Não é uma decisão de produto — é design técnico, resolver no PLN.
2. **Mensagem de fallback quando a IA não identifica um período na consulta** (ex.: "quanto eu tenho gasto?"). O worktree de referência usava "Qual período você quer consultar? Ex: 'esse mês', 'junho', 'este ano'." — decidir no SPEC se reaproveita esse texto ou define um novo, e se há um período padrão (ex.: mês corrente) em vez de sempre perguntar.
3. **Categoria em memória é suficiente, ou `get_totals_by_period` precisa devolver os itens brutos (não só a soma `entradas`/`saidas`) para permitir somar por categoria no chamador?** Hoje o método só devolve `{"entradas": float, "saidas": float}` — não devolve a lista de transações do período. Resolver no PLN: estender `get_totals_by_period`, criar um novo método de repository, ou reaproveitar `find_by_user` (que traz tudo, sem filtro de período) com filtro de período+categoria em memória no service.
4. **Texto de resposta quando a consulta (com ou sem categoria) não encontra nenhuma transação no período** — "R$ 0,00" seco ou uma frase mais amigável? Decidir no SPEC.
5. **Mensagem de fallback quando a intenção é `"nenhuma"`** — mantém o texto atual ("Não foi identificada nenhuma transação nessa mensagem...") ou atualiza para mencionar consulta também, já que agora a IA sabe distinguir os dois casos? Decidir no SPEC.
6. **Cobertura de teste do provedor de IA para o novo schema** — os testes hoje mockam a resposta JSON crua do Bedrock (`tests/services/llm/test_bedrock_provider.py`); o TASKS resultante do PLN precisa listar os novos casos (intenção consulta com período, consulta com categoria, consulta sem período identificável, mensagem `"nenhuma"`) espelhando o padrão de teste já usado.

## Próximos Passos

Classificação: **Ambíguo** — mesmo com as 3 decisões de produto já confirmadas pelo usuário nesta sessão, restam decisões técnicas reais em aberto (Perguntas 1-6) e, mais importante, **o próprio `plano-contexto.md` (linha 223) já declara que a Fase 6b ("conselhos financeiros") vai herdar o mesmo mecanismo de consulta construído aqui** — o teste de "decisão que outras tasks herdarão" do roteamento dá **Sim**, o que por si só exige rota completa independentemente do resto.

Rota: **INV (este documento) → SPEC011 → PLN011 → TASKS011**.
