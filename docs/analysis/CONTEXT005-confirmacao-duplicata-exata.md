---
type: CONTEXT
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
origem: "Relato do usuário durante uso real do bot pós-TASKS009-llama-maverick-extracao-texto.md, ao reenviar \"gastei 30 reais no mercado\" duas vezes no mesmo dia"
---

# CONTEXT005 — Bloqueio automático de `DUPLICATA_EXATA` impede reenvio legítimo de transação repetida

## Contexto

`DynamoTransactionRepository._save_one` (`repository/dynamo_repository.py`, linhas 39-67) bloqueia **sempre** quando o `sortKey` já existe, sem exceção e sem interação com o usuário — decisão deliberada, documentada em `docs/PATTERNS.md` ("Dedup determinística: fingerprint no `sortKey`, nunca em atributo próprio"): *"DUPLICATA_EXATA sempre bloqueia e nunca insere/descarta silenciosamente, mesmo em casos legítimos (ex. duas compras idênticas no mesmo dia) — decisão de produto deliberada, sem tratamento de adjacência/posição no lote."*

Essa decisão vem de `docs/specs/SPEC006-sqlite-para-dynamodb.md` / `docs/plans/PLN006-sqlite-para-dynamodb.md` / `docs/tasks/TASKS006-sqlite-para-dynamodb.md`. O `SPEC006` original chegou a cogitar uma opção **B3a** (bloquear e pedir confirmação explícita do usuário antes de gravar mesmo assim), mas o time optou pela versão sem estado na implementação — reenviar com alguma diferença já muda o fingerprint sozinho, e evita a complexidade de um fluxo de pergunta-e-espera-resposta.

## Problema

O usuário relatou, em uso real do bot (pós-`TASKS009`, já com `meta.llama4-maverick-17b-instruct-v1:0`), que mandar **"gastei 30 reais no mercado"** duas vezes seguidas no mesmo dia tem a segunda mensagem bloqueada como duplicata — comportamento esperado pela decisão acima. O ponto problemático: tentar contornar reformulando a frase (**"gastei mesmo 30 reais no mercado"**) **também é bloqueado**, mesmo a frase sendo visivelmente diferente para um humano.

## Causa raiz

O fingerprint não é calculado sobre o texto bruto do usuário, e sim sobre o campo `Transacao.descricao` **já extraído pelo LLM** — que é um rótulo curto (ex.: "mercado", "salario", "Boleto de 150" — ver exemplos reais em `docs/tasks/TASKS009-llama-maverick-extracao-texto.md`, seção T4). Pequenas variações de fraseado do usuário ("gastei" vs. "gastei mesmo") tendem a ser resumidas pelo modelo para a mesma `descricao` curta, então o fingerprint fica idêntico mesmo quando a mensagem original mudou.

Cadeia completa (`repository/dynamo_repository.py`, linhas 39-42):
```python
descricao_norm = normalize_description(t.descricao)
fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)
sort_key = f"{t.data.isoformat()}#{fingerprint}"
```
`normalize_description`/`compute_fingerprint` (`repository/dedup.py`, linhas 10-18) só tiram acento/pontuação/maiúscula e truncam o hash em 16 chars — não fazem nada com a variação de fraseado; a colisão nasce antes disso, na extração via LLM.

Bloqueio em si (`repository/dynamo_repository.py`, linhas 54-62):
```python
try:
    self._table.put_item(
        Item=item,
        ConditionExpression="attribute_not_exists(sortKey)",
    )
except ClientError as exc:
    if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
        return TransactionSaveResult(transacao=t, status="duplicata_exata")
    raise RepositoryError(f"falha ao gravar transação no DynamoDB: {exc}") from exc
```
Não há, hoje, nenhum caminho de código para "forçar" a gravação apesar do `sortKey` colidir — `ConditionExpression="attribute_not_exists(sortKey)"` falha sempre da mesma forma, incondicionalmente.

Testes que cobrem esse comportamento hoje: `tests/repository/test_dynamo_repository.py::test_put_item_condition_failure_is_duplicata_exata_and_skips_query` e `::test_cafe_bolo_cafe_same_day_second_cafe_is_duplicata_exata`; funções puras de `dedup.py` em `tests/repository/test_dedup.py`.

## Proposta do usuário (a validar)

Em vez de bloquear e descartar silenciosamente, ter um **estado de confirmação**: ao detectar `DUPLICATA_EXATA`, perguntar ao usuário (sim/não) se quer registrar mesmo assim, e só gravar (ou descartar) de acordo com a resposta.

Viabilidade técnica confirmada nesta sessão: o bot roda como processo persistente via `polling` (`main.py`, `python-telegram-bot`), não é uma função serverless por mensagem — então `context.user_data` (nativo da lib) está disponível para guardar uma "transação pendente de confirmação" por usuário, sem precisar de tabela nova no DynamoDB.

## Perguntas em aberto para quando isso virar task

- **Forçar a gravação apesar do `sortKey` idêntico**: se o usuário confirmar "sim, registra mesmo assim", o `PutItem` condicional vai falhar de novo (mesmo fingerprint) — precisa de um jeito de escrever um item com `sortKey` diferente nesse caso (`PLN006` cogitou e descartou um sufixo de sequência para isso; precisa reabrir essa decisão agora com um motivo concreto).
- **Timeout de resposta**: o que fazer se o usuário nunca responde sim/não? Não gravar nunca? Expirar depois de X tempo e descartar? Expirar e gravar como estava antes (bloqueado)?
- **Mensagens intercaladas**: o que fazer se o usuário manda outra transação nova antes de confirmar a pendente — o estado por usuário suporta só 1 pendência, ou precisa de fila?
- **Persistência do estado**: `context.user_data` é em memória, por processo — se o bot reiniciar (deploy, crash), a pendência se perde silenciosamente sem o usuário saber. Aceitável para esse fluxo, ou precisa sobreviver a restart (o que reabriria a discussão de "sem estado" de forma mais séria)?
- **Janela de recência**: vale bloquear só quando é o mesmo dia+valor+tipo+descrição (comportamento atual), ou introduzir uma janela mais curta (ex.: poucos minutos) para distinguir "reenviei sem querer" de "comprei a mesma coisa duas vezes hoje de propósito"?

## Addendum — três correções propostas pelo usuário (a validar no `/map-task`)

**Correção 1 — idempotência de infraestrutura via `update_id`/`message_id` do Telegram.** Antes de qualquer extração via LLM, gravar o `update_id` (ou `message.message_id`, ambos acessíveis em `handlers/text_handler.py:9-11` via `update.update_id`/`update.message.message_id`) já processado, e descartar sem chamar o LLM se repetido. Correta como princípio — resolve sem ambiguidade o caso de a **mesma entrega** ser reprocessada (reentrega de webhook, restart do bot no meio do processamento). **Ressalva importante:** isso não é a causa do bug relatado nesta CONTEXT — "gastei 30 reais no mercado" e "gastei mesmo 30 reais no mercado" são duas mensagens genuinamente distintas do usuário, com `update_id`/`message_id` diferentes. Idempotência técnica é complementar à Correção 2, não substitui — não reduz a necessidade do fluxo de confirmação por conteúdo.

**Correção 2 — reclassificar o hash de conteúdo como sinal de SUSPEITA, nunca bloqueio automático.** Com a idempotência técnica cuidando de "mesma entrega duas vezes" (Correção 1), o hash de `valor+tipo+descricao_normalizada` deixaria de justificar bloqueio automático — viraria sempre `SUSPEITA` (pedindo confirmação), nunca mais `DUPLICATA_EXATA` bloqueando sozinho. Coerente com a pergunta já aberta nesta CONTEXT ("Proposta do usuário", acima) — é a mesma direção, só com uma justificativa técnica mais forte pra abandonar o bloqueio automático (a idempotência de infra já cobre o caso que o bloqueio automático tentava evitar por engano). **Não elimina** o problema já registrado em "Perguntas em aberto": se o usuário confirmar "sim, registra mesmo assim", o `PutItem` condicional ainda falha com o mesmo fingerprint no `sortKey` — a forma de forçar a gravação continua sem solução, precisa ser decidida no SPEC/PLN.

**Correção 3 — janela de tempo para calibrar a mensagem de confirmação.** Dentro do estado `SUSPEITA`, usar o intervalo entre as duas transações para adaptar o texto da pergunta ao usuário: poucos segundos → provável duplo-envio, pergunta com peso pra "foi sem querer"; minutos/horas → mais provável ser compra real repetida, pergunta mais neutra. Boa ideia de UX, mas depende de um sinal que **não existe hoje** no domínio: `models.Transacao.data` é só `date`, sem hora (`models.py:10`) — implementar isso exige guardar o horário real de chegada da mensagem em algum lugar separado do campo de negócio `data` (não é gratuito, é uma decisão nova pro SPEC/PLN: onde esse timestamp vive, e se ele deveria fazer parte do DTO/Entity ou ficar fora, ao lado do fluxo de dedup).

## Recomendação

Investigar como task própria via `/map-task`, com rota completa (SPEC → PLN), não rota curta: a mudança reverte uma decisão de produto já documentada em três lugares (`SPEC006`, `PLN006`, `TASKS006`/`PATTERNS.md`), introduz o primeiro fluxo com estado de conversação do bot (hoje 100% stateless), e agora também uma camada nova de idempotência técnica (`update_id`) e um sinal de tempo que ainda não existe no domínio — decisões que outras funcionalidades futuras (ex. edição de transação, `CONTEXT003`) podem querer reaproveitar, então merece o mesmo nível de rigor que `SPEC006` teve, não um ajuste pontual.
