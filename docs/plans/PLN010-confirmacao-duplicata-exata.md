---
type: PLN
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Draft
spec: docs/specs/SPEC010-confirmacao-duplicata-exata.md
inv: docs/analysis/INV008-confirmacao-duplicata-exata.md
---

# PLN010 — Estratégia técnica para confirmação com estado (`DUPLICATA_EXATA`/`SUSPEITA`)

## Escopo confirmado nesta sessão

- Implementação **só em `DynamoTransactionRepository`** (backend ativo via `.env`, `DB_BACKEND=dynamo`). `SqliteTransactionRepository` continua com o comportamento atual (bloqueio/nota informativa) — os métodos novos de pendência/idempotência **não** entram no ABC `TransactionRepository` como abstratos, ficam como extensão específica do Dynamo. Os dois backends deixam de ter paridade de comportamento nesta funcionalidade — aceito, decisão desta sessão.
- Nenhuma dependência nova (confirma Non-Goal do SPEC — sem `APScheduler`). Toda a estratégia usa só recursos já disponíveis no `boto3`/DynamoDB (Query, PutItem condicional, TTL nativo) e no `python-telegram-bot` já instalado (`InlineKeyboardButton`, `CallbackQueryHandler`).

## Estratégia

### 1. Novo tipo de Item: pendência de confirmação

Mesma tabela, mesmo padrão de `ConfigItem` (`docs/PATTERNS.md`, "Configuração é um único tipo de Item"):

```
userId: "<telegram_user_id>"
sortKey: "PENDENTE#<uuid4().hex>"
motivo: "duplicata_exata" | "suspeita"
transacao: {data, descricao, valor, tipo, categoria}   # snapshot da candidata
similares: [{data, descricao, valor, tipo, categoria}, ...]  # snapshot, não referência viva
criadoEm: "<ISO datetime UTC>"   # timestamp de chegada da mensagem candidata (Correção 3)
```

Novo Pydantic model em `repository/provider.py` (ao lado de `TransactionSaveResult`/`ConfigItem`, mesmo arquivo, sem módulo novo):

```python
class PendingConfirmation(BaseModel):
    id: str
    transacao: Transacao
    motivo: Literal["duplicata_exata", "suspeita"]
    similares: list[Transacao] = []
    criado_em: datetime
```

### 2. Timestamp de chegada em toda transação gravada (Problema 5 / Correção 3)

Em vez de threadar `update.message.date` do handler até o repository (mudaria assinatura de `save_transactions` em 3 handlers + service + ABC + 2 implementações), o timestamp é capturado **dentro do repository**, uma vez por chamada de `save_transactions` (não por item), com `datetime.now(timezone.utc)`. A diferença entre "mensagem chegou" e "repository processou" é de segundos (tempo de LLM já rodou antes) — irrelevante para a granularidade do R17 ("segundos/minutos" vs. "horas"). Vira um novo atributo `criadoEm` em **todo** Item de transação real (não só nas pendências), gravado na camada de dados — **não** entra em `models.Transacao` (DTO), confirma Non-Goal do SPEC. `_item_to_transacao` continua ignorando esse atributo ao reconstruir o DTO.

**Itens antigos sem `criadoEm`** (gravados antes desta task): tratados, ao calcular o intervalo do R17, como se tivessem `criadoEm` à meia-noite UTC da própria `data` de negócio — garante que sempre caem no branch de "intervalo longo/neutro", nunca sugerem duplo-envio para dado histórico.

### 3. `_save_one` reescrito: de bloqueio/gravação imediata para pendência

**Antes** (`repository/dynamo_repository.py:39-67`, resumido):
```python
try:
    self._table.put_item(Item=item, ConditionExpression="attribute_not_exists(sortKey)")
except ClientError as exc:
    if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
        return TransactionSaveResult(transacao=t, status="duplicata_exata")  # nunca grava
    raise ...
similares = await self._find_similar(...)
if similares:
    return TransactionSaveResult(transacao=t, status="suspeita", similares=similares)  # já gravou
return TransactionSaveResult(transacao=t, status="nova")
```

**Depois** (estrutura, não código final — detalhamento fica para o TASKS):
```python
async def _save_one(self, t, telegram_user_id, criado_em):
    descricao_norm = normalize_description(t.descricao)
    fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)
    sort_key = f"{t.data.isoformat()}#{fingerprint}"

    exact_match = await self._find_exact(user_id, sort_key)          # R3 — só transações confirmadas
    if exact_match:
        pendencia = await self._create_pending(user_id, t, "duplicata_exata", [exact_match], criado_em)
        return TransactionSaveResult(transacao=t, status="duplicata_exata", pendencia_id=pendencia.id)

    similares = await self._find_similar(user_id, t, descricao_norm, exclude_sort_key=sort_key)  # R4/R6 — transações confirmadas + PENDENTE#
    if similares:
        pendencia = await self._create_pending(user_id, t, "suspeita", similares, criado_em)
        return TransactionSaveResult(transacao=t, status="suspeita", pendencia_id=pendencia.id)

    await self._table.put_item(Item={**item, "criadoEm": criado_em.isoformat()})  # sem ConditionExpression: já sabemos que não colide
    return TransactionSaveResult(transacao=t, status="nova")
```

`_find_similar` (R6) passa a rodar **duas** Queries: a já existente (transações reais na janela de `SUSPECT_WINDOW_DAYS`) e uma nova (`sortKey` começando com `"PENDENTE#"` do mesmo usuário, com `FilterExpression` no atributo embutido `transacao.data` dentro da mesma janela) — resultado combinado antes de aplicar `is_similar`.

`TransactionSaveResult` (`repository/provider.py`) ganha um campo novo `pendencia_id: str | None = None`, para o handler saber qual pendência mostrar com botões (R12).

### 4. Confirmar ("Sim") força a gravação sem re-colidir

`PLN006` cogitou e descartou um sufixo de sequência no `sortKey` por não ter, na época, um motivo concreto — agora tem: ao confirmar, o `sortKey` final passa a ser `f"{data}#{fingerprint}#{pendencia_id}"` (reaproveita o mesmo `id` da pendência, já único), e o `PutItem` roda **sem** `ConditionExpression` — a decisão já foi validada pelo usuário, não há mais nada para checar. Efeito colateral aceito: um "Sim" confirmado deixa de ser pego por `_find_exact` (R3) numa colisão futura exata (porque o `sortKey` tem sufixo), mas **sempre** é pego por `_find_similar` (R4) — já que a descrição normalizada de um duplicado exato bate 100% (`is_similar` retorna 1.0, acima do `SIMILARITY_THRESHOLD`). Ou seja, o duplicado futuro ainda vira pendência, só que classificado como `suspeita` em vez de `duplicata_exata` — mudança de rótulo, não de comportamento (documentado aqui para não ser redescoberto como bug depois).

### 5. Resolução da pendência ("Sim"/"Não")

Novo método `resolve_pending(telegram_user_id, pendencia_id, decisao)`:
- **Sim**: lê o Item `PENDENTE#{id}`, grava a transação com o `sortKey` sufixado (item 4) usando o `criadoEm` **original** guardado na pendência (não o momento da resposta — preserva a semântica do R17 mesmo se a confirmação vier dias depois), depois **apaga** o Item de pendência com `ConditionExpression="attribute_exists(sortKey)"` (evita dupla-gravação em caso de duplo toque no botão — ver Riscos).
- **Não**: apaga o Item de pendência (mesma condição de existência), sem gravar nada.
- Se a condição falhar em qualquer um dos dois casos (pendência já resolvida por outro toque), o método retorna um resultado "já resolvida" — o handler edita a mensagem avisando isso, sem re-processar.

Novo método `find_pending_by_user(telegram_user_id) -> list[PendingConfirmation]`: `Query` por `userId` + `sortKey` começando com `"PENDENTE#"`.

### 6. Idempotência de entrega (`update_id`/`message_id`, Correção 1)

Item separado, mesma tabela:
```
userId: "<telegram_user_id>"
sortKey: "PROCESSADO#<update_id>"
expiraEm: <epoch seconds, agora + 24h>   # atributo de TTL nativo do DynamoDB
```
Novo método `try_claim_update(telegram_user_id, update_id) -> bool`: `PutItem` com `ConditionExpression="attribute_not_exists(sortKey)"`; `True` se gravou (primeira vez), `False` se `ConditionalCheckFailedException` (já processado). TTL nativo do DynamoDB expira o item sozinho depois de 24h (R2 — janela recente, não retenção permanente); a expiração do TTL do DynamoDB não é instantânea (pode levar até algumas horas além do previsto), o que é aceitável aqui porque o objetivo é só cobrir reentrega de curto prazo, não uma garantia de limpeza exata.

Chamado no início de cada handler (`text_handler.py`, `photo_handler.py`, `pdf_handler.py`), antes de qualquer chamada ao LLM:
```python
if not await claim_update(user_id, update.update_id):
    return
```
Mesmo padrão de guarda já existente nos handlers (ex.: checagem de tamanho de arquivo em `photo_handler.py:16-18`) — não é lógica de negócio nova na camada de handler, é o mesmo tipo de curto-circuito técnico já presente.

### 7. Superfícies de interação (R11/R12/R13/R14)

- **R12 (botões imediatos)**: quando um item do lote resultar em `status in ("suspeita", "duplicata_exata")`, o handler envia uma mensagem **separada** para aquele item (além da mensagem-resumo já existente para os itens `nova`), com `InlineKeyboardMarkup` de dois botões (`callback_data="pend:sim:<id>"` / `"pend:nao:<id>"`). Isso muda a forma de resposta hoje (uma única mensagem combinada) para: 1 mensagem-resumo (itens `nova`) + N mensagens (uma por pendência do lote), consistente com R11 (lote não trava, cada pendência é resolvida independentemente).
- **R13 (`/pendencias`)**: novo `CommandHandler("pendencias", ...)` em `handlers/pending_handler.py`, lista todas as pendências abertas do usuário (`find_pending_by_user`), uma mensagem por pendência com o mesmo formato de botões do R12 — o mesmo `CallbackQueryHandler` resolve os dois casos, sem distinguir a origem.
- **R15 (calibração de tempo)**: o texto da pendência (usado tanto em R12 quanto em R13) calcula o intervalo entre `criadoEm` da candidata e `criadoEm` da(s) similar(es)/original, formatando o texto de acordo (função pura nova, testável, em `services/message_service.py`).

## Alternativas Consideradas e Descartadas

- **Threadar `update.message.date` do handler até o repository** para o timestamp de chegada (em vez de capturar `datetime.now(UTC)` no repository) — descartado por exigir mudar a assinatura de `save_transactions` em toda a cadeia (3 handlers, service, ABC, 2 implementações) por uma precisão de poucos segundos que não muda nenhuma decisão do R17 (que só distingue "segundos/minutos" de "horas/dias").
- **`PutItem` condicional na gravação confirmada ("Sim")** (mantendo a proteção de `ConditionExpression`) — descartado porque, com o `sortKey` sufixado por um `id` de pendência único, a colisão é estruturalmente impossível; a condição só adicionaria uma chamada extra sem proteger contra nada.
- **Um único Item de pendência por lote** (em vez de um Item por transação candidata) — descartado: quebraria R11 (cada pendência do lote precisa ser resolvida independentemente, com seu próprio botão) e complicaria o "Não" parcial (rejeitar 1 de 3 pendências do mesmo lote).
- **Implementar em `SqliteTransactionRepository` também** — descartado nesta sessão (ver "Escopo confirmado").

## Arquivos a Modificar

- `repository/provider.py` — novo `PendingConfirmation`; `TransactionSaveResult` ganha `pendencia_id: str | None = None`; `TransactionRepository` (ABC) **não** ganha os métodos novos como abstratos (ficam só em `DynamoTransactionRepository`, ver Escopo).
- `repository/dynamo_repository.py` — `_save_one` reescrito (item 3); novos métodos `_find_exact`, `_create_pending`, `resolve_pending`, `find_pending_by_user`, `try_claim_update`; `_find_similar` passa a incluir Query de `PENDENTE#` (R6).
- `repository/dedup.py` — sem mudança de lógica pura; talvez um helper novo para calcular o texto calibrado por intervalo (a decidir no TASKS se fica aqui ou em `message_service.py`).
- `services/transaction_service.py` — expõe `get_pending`, `resolve_pending`, `claim_update` (repasse direto ao repository, mesmo padrão de repasse já usado no arquivo).
- `services/message_service.py` — nova função de formatação por pendência (texto + calibração de tempo, R15); `format_message` para itens `nova` continua como está.
- `handlers/text_handler.py`, `handlers/photo_handler.py`, `handlers/pdf_handler.py` — chamada a `claim_update` no início; loop novo para enviar uma mensagem por pendência (R12) além do resumo de `nova`.
- `handlers/pending_handler.py` (**novo arquivo**) — `CommandHandler("pendencias", ...)` (R13) e `CallbackQueryHandler` de resolução (R14), compartilhado entre R12 e R13.
- `main.py` — registra `CommandHandler("pendencias", ...)` e o `CallbackQueryHandler` novo.
- `tests/repository/test_dynamo_repository.py` — reescreve `test_put_item_condition_failure_is_duplicata_exata_and_skips_query`, `test_cafe_bolo_cafe_same_day_second_cafe_is_duplicata_exata`, `test_save_transaction_with_similar_candidate_is_suspeita`, `test_save_new_transaction_excludes_itself_from_suspeita_check` para o novo comportamento (pendência, não bloqueio/gravação imediata); testes novos para `_find_exact`/`_create_pending`/`resolve_pending`/`find_pending_by_user`/`try_claim_update`.
- `docs/PATTERNS.md` — nova entrada em "Decisões Estabelecidas" registrando: (a) pendência de confirmação como Item persistido (padrão reaproveitável por features futuras com necessidade parecida); (b) `criadoEm` como atributo de Entity/Item, nunca de DTO; (c) escopo Dynamo-only desta funcionalidade.

## Riscos

- **Duplo toque no botão "Sim"/"Não"** antes do primeiro processar — mitigado por `ConditionExpression="attribute_exists(sortKey)"` na exclusão da pendência (item 5); o segundo toque falha a condição e o handler responde "já resolvida" em vez de gravar duas vezes.
- **Custo de leitura adicional**: cada `_save_one` agora faz até 2 Queries (janela de transações + janela de `PENDENTE#`) em vez de 1 — aceitável para o volume pessoal do projeto (já discutido em `docs/specs/SPEC008-nova-lite-extracao-documento.md`), mas TASKS deve confirmar que não introduz throttling perceptível em teste manual.
- **`callback_data` do Telegram tem limite de 64 bytes** — `f"pend:sim:{uuid4().hex}"` (9 + 32 = 41 chars) fica dentro do limite; não usar um `id` mais longo que isso no futuro sem revisar.
- **Itens de transação antigos sem `criadoEm`** — cobertos pelo fallback de meia-noite (item 2); não é migração de dados, é tratamento de ausência de atributo em runtime.
- **Paridade quebrada entre backends** (Dynamo com pendência, SQLite sem) — aceito nesta sessão; se o projeto voltar a usar SQLite como backend ativo no futuro, este PLN não cobre esse caso e precisará de trabalho adicional.
