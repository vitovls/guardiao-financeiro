---
type: INV
version: 1.2.0
author: Victor Veloso
date: 2026-07-28
status: Draft
origem: "docs/analysis/CONTEXT005-confirmacao-duplicata-exata.md"
---

# INV008 — Bloqueio automático de `DUPLICATA_EXATA` e semântica de `SUSPEITA` precisam de um fluxo de confirmação com estado

## Contexto

Gatilho: relato do usuário em uso real do bot, pós-`TASKS009-llama-maverick-extracao-texto.md` — mandar "gastei 30 reais no mercado" duas vezes no mesmo dia tem a segunda mensagem bloqueada como duplicata (comportamento hoje esperado). Reformular a frase ("gastei mesmo 30 reais no mercado") também é bloqueado, apesar de ser uma mensagem visivelmente diferente para um humano. Investigação completa e primeira rodada de perguntas em aberto já está em `docs/analysis/CONTEXT005-confirmacao-duplicata-exata.md`; este INV consolida a investigação de código, adiciona uma descoberta que o CONTEXT005 não cobria, e registra as decisões de escopo já confirmadas pelo usuário nesta sessão de `/map-task`.

Branch atual: `main` (nenhuma branch de feature criada ainda — obrigatória antes de qualquer implementação, ver `CLAUDE.md` seção Branches).

## Problema 1 — `DUPLICATA_EXATA` bloqueia incondicionalmente, sem exceção

### Descrição observada

`DynamoTransactionRepository._save_one` bloqueia sempre que o `sortKey` (`{data ISO}#{fingerprint}`) já existe, sem nenhum caminho de código para forçar a gravação mesmo assim. Duas mensagens de usuário genuinamente diferentes ("gastei 30 reais no mercado" / "gastei mesmo 30 reais no mercado") colidem porque o LLM extrai a mesma `descricao` curta para as duas ("mercado"), e o fingerprint é calculado sobre essa `descricao` já extraída, não sobre o texto bruto.

### Análise de causa raiz

`repository/dynamo_repository.py:40-42`:
```python
descricao_norm = normalize_description(t.descricao)
fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)
sort_key = f"{t.data.isoformat()}#{fingerprint}"
```
`repository/dedup.py:10-18` (`normalize_description`/`compute_fingerprint`) só tira acento/pontuação/maiúscula e faz hash truncado em 16 chars — não lida com variação de fraseado; a colisão nasce antes, na extração via LLM (rótulo curto e determinístico o bastante para gerar o mesmo texto a partir de frases diferentes).

Bloqueio em si, `repository/dynamo_repository.py:54-62`:
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
`ConditionExpression="attribute_not_exists(sortKey)"` falha sempre da mesma forma — não há hoje nenhum parâmetro/flag que permita "gravar mesmo assim".

Decisão de produto documentada e deliberada em `docs/PATTERNS.md` ("Dedup determinística: fingerprint no `sortKey`, nunca em atributo próprio"): *"DUPLICATA_EXATA sempre bloqueia e nunca insere/descarta silenciosamente, mesmo em casos legítimos... decisão de produto deliberada, sem tratamento de adjacência/posição no lote."* Origem: `docs/specs/SPEC006-sqlite-para-dynamodb.md` (opção B3a cogitada e descartada) / `docs/plans/PLN006-sqlite-para-dynamodb.md` / `docs/tasks/TASKS006-sqlite-para-dynamodb.md`.

### Arquivos relevantes

- `repository/dynamo_repository.py:39-67` (`_save_one`)
- `repository/dedup.py:1-18` (`normalize_description`, `compute_fingerprint`)
- `docs/PATTERNS.md:79-81` ("Dedup determinística")
- Testes: `tests/repository/test_dynamo_repository.py::test_put_item_condition_failure_is_duplicata_exata_and_skips_query`, `::test_cafe_bolo_cafe_same_day_second_cafe_is_duplicata_exata`

## Problema 2 — `SUSPEITA` já existe hoje como sinal não-bloqueante e colide semanticamente com a Correção 2 proposta

### Descrição observada

**Descoberta desta sessão, não coberta pelo CONTEXT005.** O repositório já implementa um segundo mecanismo de dedup, mais permissivo, para transações *parecidas mas não idênticas*: quando o `PutItem` do fingerprint exato tem sucesso (ou seja, não é `DUPLICATA_EXATA`), o código busca candidatos similares numa janela de 90 dias e, se achar, retorna `status="suspeita"` — mas **grava a transação normalmente**, sem pedir nada ao usuário. `services/message_service.py` só anexa uma nota informativa ("parece semelhante a uma já registrada") na mensagem de resposta.

A Correção 2 do CONTEXT005 (addendum) propõe: *"o hash de conteúdo... deixaria de justificar bloqueio automático — viraria sempre `SUSPEITA` (pedindo confirmação), nunca mais `DUPLICATA_EXATA` bloqueando sozinho."* Isso usa a palavra "SUSPEITA" com um significado novo (bloqueia até confirmação) que colide com o significado atual do status homônimo em produção (nunca bloqueia).

### Análise de causa raiz

`repository/dynamo_repository.py:64-95`:
```python
similares = await self._find_similar(user_id, t, descricao_norm, exclude_sort_key=sort_key)
if similares:
    return TransactionSaveResult(transacao=t, status="suspeita", similares=similares)
return TransactionSaveResult(transacao=t, status="nova")
```
`_find_similar` usa `SUSPECT_WINDOW_DAYS = 90` (`repository/dedup.py:7`) e `is_similar` (`SequenceMatcher`, `SIMILARITY_THRESHOLD = 0.8`, `repository/dedup.py:21-22`) para achar transações de mesmo `valor`+`tipo` com descrição textualmente parecida, dentro de uma janela de 90 dias — mas isso roda **depois** do `put_item` já ter sucesso, ou seja, a transação já está persistida quando a checagem de similaridade acontece.

`services/message_service.py:43,49-50`:
```python
emoji = "🟡" if r.status == "suspeita" else (...)
...
if r.status == "suspeita":
    notes.append("parece semelhante a uma já registrada")
```
Nenhum ponto do fluxo espera resposta do usuário — é puramente informativo.

**Decisão confirmada pelo usuário nesta sessão:** reaproveitar o nome/status `"suspeita"` e **mudar seu comportamento** — tanto o caso de hash exato colidindo quanto o caso já existente de descrição similar dentro da janela de 90 dias passam a exigir confirmação sim/não antes de gravar. Isso é uma **mudança de comportamento em funcionalidade já em produção** desde `TASKS006-sqlite-para-dynamodb.md`, não uma extensão puramente aditiva — os testes atuais que assumem gravação imediata sem confirmação (`test_save_transaction_with_similar_candidate_is_suspeita`, `test_save_new_transaction_excludes_itself_from_suspeita_check`) vão precisar ser revistos/reescritos no SPEC/PLN.

### Arquivos relevantes

- `repository/dynamo_repository.py:64-95` (`_save_one`, `_find_similar`)
- `repository/dedup.py:6-7,21-22` (`SUSPECT_WINDOW_DAYS`, `is_similar`, `SIMILARITY_THRESHOLD`)
- `repository/provider.py:14-17` (`TransactionSaveResult`, `Literal["nova", "suspeita", "duplicata_exata"]`)
- `services/message_service.py:43,49-50` (nota informativa atual)
- Testes: `tests/repository/test_dynamo_repository.py::test_save_transaction_with_similar_candidate_is_suspeita`, `::test_save_new_transaction_excludes_itself_from_suspeita_check`

## Problema 3 — Nenhum handler hoje trata resposta de confirmação; bot é 100% stateless por desenho

### Descrição observada

Não existe, em nenhum lugar do código, qualquer mecanismo de: capturar uma resposta do usuário e correlacioná-la a uma pendência anterior. Seria a primeira introdução de um fluxo com estado de conversação no bot.

### Análise de causa raiz

`main.py:16-19` registra só três `MessageHandler` incondicionais, todos despachando direto para extração/gravação:
```python
app.add_handler(MessageHandler(filters.TEXT, get_message))
app.add_handler(MessageHandler(filters.PHOTO, get_photo))
app.add_handler(MessageHandler(filters.Document.PDF, get_pdf))
```
Nenhum `ConversationHandler` ou `CallbackQueryHandler` está registrado — busca confirmada via grep no projeto inteiro (só ocorrências dentro de `venv/`, nenhuma no código do projeto). Toda mensagem de texto (`handlers/text_handler.py:9-19`) vai direto para `extract_text_transactions` (chamada ao LLM) — não há checagem de "este usuário tem uma pendência de confirmação aguardando resposta" antes de extrair uma transação nova.

Isso afeta os três pontos de entrada igualmente: `text_handler.py`, `photo_handler.py` e `pdf_handler.py` chamam todos `services/transaction_service.py::save_transactions`, que repassa direto ao repository (`services/transaction_service.py:8-10`) — qualquer novo fluxo de confirmação precisa decidir em que camada intercepta (handler? service? repository retorna um status pendente e o handler decide o que fazer com ele?).

Precisa de decisão de design (SPEC/PLN): capturar a resposta sim/não como **texto livre interceptado antes do `MessageHandler` de extração** (risco: colide com o parser de texto livre se o usuário responder algo ambíguo) ou como **`InlineKeyboardButton` + `CallbackQueryHandler`** (mais robusto, mas exige novo tipo de handler no projeto, ainda inexistente).

Viabilidade confirmada no CONTEXT005: o bot roda como processo persistente via `polling` (não serverless por mensagem), então `context.user_data` (nativo do `python-telegram-bot`) está disponível para guardar uma "transação pendente de confirmação" por usuário, sem tabela nova no DynamoDB.

### Arquivos relevantes

- `main.py:12-21` (registro de handlers)
- `handlers/text_handler.py:1-25`, `handlers/photo_handler.py:1-41`, `handlers/pdf_handler.py:1-45` (três pontos de entrada, mesma necessidade)
- `services/transaction_service.py:1-21` (camada de repasse, hoje sem lógica)

## Problema 4 — Ausência de idempotência de infraestrutura (`update_id`/`message_id`)

### Descrição observada

Não há hoje nenhuma checagem de mensagem/update já processado. Uma reentrega de webhook ou um restart do bot no meio do processamento reprocessaria a mesma mensagem do zero, chamando o LLM de novo e potencialmente gerando um resultado diferente para a mesma entrega técnica.

### Análise de causa raiz

`handlers/text_handler.py:9-11` recebe `update: Update` mas nunca lê `update.update_id` nem `update.message.message_id` — ambos disponíveis via `python-telegram-bot`, mas não usados em lugar nenhum do projeto (confirmado por leitura de todos os handlers). Correção 1 do CONTEXT005 propõe gravar esses IDs já processados e descartar sem chamar o LLM se repetido.

**Importante (já registrado no CONTEXT005, reafirmado aqui):** isso é ortogonal ao Problema 1 — resolve "mesma entrega processada duas vezes", não "usuário mandou duas mensagens de conteúdo parecido de propósito ou por engano". As duas frases do relato original ("gastei 30 reais no mercado" / "gastei mesmo 30 reais no mercado") têm `update_id`/`message_id` diferentes — a idempotência técnica não teria evitado o bloqueio relatado.

### Arquivos relevantes

- `handlers/text_handler.py:9-11` (onde `update_id`/`message_id` estariam disponíveis e não são lidos)
- Nenhum arquivo de armazenamento de IDs processados existe hoje (nem em memória, nem no DynamoDB)

## Problema 5 — Ausência de timestamp real de chegada da mensagem

### Descrição observada

A Correção 3 do CONTEXT005 (calibrar o texto de confirmação pela proximidade temporal — segundos sugerem duplo-envio, minutos/horas sugerem compra real repetida) depende de um sinal que não existe hoje em nenhuma camada do domínio.

### Análise de causa raiz

`models.py:9-14` (`Transacao`) só tem `data: date` — sem hora. Nenhuma Entity, Item do DynamoDB, ou estrutura em memória guarda o horário real de chegada de uma mensagem hoje. Introduzir esse timestamp é decisão nova para o SPEC/PLN: onde ele vive (dentro do próprio estado de pendência de confirmação em `context.user_data`, sem tocar `Transacao`/DTO, parece o caminho que menos invade o domínio existente — mas precisa ser confirmado formalmente, não presumido aqui).

### Arquivos relevantes

- `models.py:9-14` (`Transacao`, campo `data: date` sem hora)

## Problema 6 — Uma única mensagem já produz N transações; confirmação em lote não tem desenho hoje

### Descrição observada

**Aprofundamento pedido pelo usuário nesta sessão.** Os três pontos de entrada (`text_handler`, `photo_handler`, `pdf_handler`) sempre retornam `list[Transacao]`, nunca uma transação isolada — inclusive texto livre pode descrever mais de uma transação na mesma mensagem. Uma única foto de extrato ou PDF de fatura tipicamente produz várias transações de uma vez. Hoje, `save_transactions` (`services/transaction_service.py:8-10`) itera cada uma via `_save_one` (`repository/dynamo_repository.py:37`) e cada item recebe seu próprio status (`nova`/`suspeita`/`duplicata_exata`) **de forma independente**, e o resultado combinado do lote inteiro vira uma única mensagem formatada (`services/message_service.py::format_message`, que já itera `list[TransactionSaveResult]` e monta um resumo agregando entradas/saídas de todo o lote).

Se `SUSPEITA` passa a exigir confirmação (Decisão de Produto já registrada acima), uma única foto pode gerar **múltiplas pendências de confirmação simultâneas para o mesmo usuário, nascidas do mesmo lote** — não é o mesmo cenário da já registrada "mensagens intercaladas" (que trata de uma mensagem *nova* chegando enquanto uma pendência de uma mensagem *anterior* ainda aguarda resposta). Aqui o lote inteiro chega de uma vez e uma fração dele (não necessariamente todas) precisa de confirmação.

### Análise de causa raiz

`services/transaction_service.py:8-10`:
```python
async def save_transactions(transactions: list[Transacao], telegram_user_id: int) -> list[TransactionSaveResult]:
    repository = get_transaction_repository()
    return await repository.save_transactions(transactions, telegram_user_id)
```
`DynamoTransactionRepository.save_transactions` (`repository/dynamo_repository.py:34-37`) processa a lista sequencialmente, um `_save_one` por vez, sem noção de "lote" nem de agrupar itens que precisam de confirmação separadamente dos que não precisam. Não há hoje nenhum desenho de：
- confirmar o lote inteiro de uma vez (uma pergunta agregada: "destas 5 transações, 2 parecem repetidas — confirma as duas?"),
- ou confirmar item por item em sequência (uma fila dentro do próprio lote, além da fila entre mensagens diferentes),
- ou salvar de imediato as que são `nova` e só perguntar pelas que são `suspeita`/`duplicata_exata` (parcial, precisa decidir se a resposta parcial do lote é reportada numa mensagem só ou em mensagens separadas).

### Arquivos relevantes

- `services/transaction_service.py:8-10` (`save_transactions`, repasse direto sem agrupamento)
- `repository/dynamo_repository.py:34-37` (`save_transactions`, itera sequencial via `_save_one`)
- `services/message_service.py:26-65` (`format_message`, já agrega `list[TransactionSaveResult]` numa única mensagem — precisa decidir se channels de confirmação pendente entram nesse mesmo relatório ou em mensagens separadas)

## Investigação: pendências persistidas + revisão sob demanda ("check-in semanal") — não é a Fase 6b em si

**Aprofundamento pedido pelo usuário nesta sessão, refinado em uma segunda rodada.** A ideia original ("o agente de conselho ajuda nisso") foi corrigida pelo próprio usuário: não é o agente de conselho (LLM, Fase 6b) que resolveria a ambiguidade sozinho — é um **sistema de consulta às pendências de `SUSPEITA`**, que poderia ser chamado tanto num check-in semanal (ou periodicidade parecida) quanto, no futuro, por um agente. São duas coisas separadas: (a) a pendência precisa existir como **dado consultável**, não só como um sim/não que expira; (b) *quem* ou *o quê* aciona essa consulta (comando manual, mensagem semanal proativa do bot, ou futuramente o agente de conselho como uma de suas ferramentas) é uma decisão de superfície, independente de (a).

### Achado 1 — a Fase 6b (agente de conselho) segue não implementada

Confirmado na rodada anterior: `docs/analysis/fase3-lacuna-dynamo-arquitetura.md` e `docs/analysis/plano-contexto.md:205-211,295-299` — Fase 6b é conceitual, zero código, depende de Fase 6a (consulta pura) e de uma modelagem de orçamento que também não existe. Não muda com este refinamento; o usuário confirmou que não é essa a peça em jogo aqui.

### Achado 2 — persistir a pendência em vez de `context.user_data` é tecnicamente necessário para esta ideia funcionar, e resolve duas Perguntas em Aberto de uma vez

O CONTEXT005 (e a primeira rodada deste INV) presumiam `context.user_data` — em memória, por processo — como suficiente para guardar "uma transação pendente de confirmação". Isso deixa de ser viável se a pendência precisa sobreviver até um check-in *semanal*: memória de processo não sobrevive a um restart/deploy no meio da semana, e a proposta do usuário pressupõe explicitamente que a pendência ainda esteja lá dias depois.

Isso empurra o desenho para persistir a pendência como um **Item do DynamoDB**, seguindo o mesmo padrão já estabelecido para configuração (`docs/PATTERNS.md:91-93`, "Configuração é um único tipo de Item, sem ABC de repository" — `ConfigItem`/`sortKey = "CONFIG#{nome}"`). Um item análogo, por exemplo `sortKey = "PENDENTE#{sortKey_da_transacao}"`, guardando a `Transacao` completa, o motivo (`duplicata_exata`/`suspeita`), os candidatos similares e o momento de criação, é consistente com o design single-table já em uso (mesma tabela, mesmo `userId` como partition key).

Isso **resolve, por construção**, duas Perguntas em Aberto já registradas:
- **Pergunta 4 (persistência do estado)**: deixa de ser uma escolha entre "aceitar perda em restart" ou "reabrir sem estado" — um Item persistido sobrevive a restart pela mesma garantia que qualquer outra transação já salva.
- **Pergunta 2 (timeout sem perda silenciosa)**: deixa de precisar de um timeout que descarta. A pendência simplesmente continua existindo como um Item consultável até o usuário resolvê-la — imediatamente após a mensagem, ou dias depois num check-in. Nada precisa expirar.
- Também simplifica as **Perguntas 3a/3b (filas)**: se pendências são linhas persistidas e consultáveis por `userId`, múltiplas pendências (entre mensagens ou dentro do mesmo lote) deixam de exigir uma máquina de estados de fila em memória — é só uma `Query` retornando todos os itens `PENDENTE#` do usuário.

### Achado 3 — viabilidade técnica da superfície "check-in": comando sob demanda é imediato; push proativo semanal exige nova dependência

Duas superfícies possíveis para o usuário revisar pendências, com viabilidades bem diferentes:

- **Comando/consulta sob demanda** (ex.: usuário manda `/pendencias` ou pergunta em texto livre): viável hoje sem nenhuma dependência nova — é só mais um `MessageHandler`/`CommandHandler` (`python-telegram-bot` já usado) chamando um novo método do repository que faz `Query` nos itens `PENDENTE#` do usuário. Mesmo padrão arquitetural já usado em todo o projeto (handler → service → repository).
- **Push proativo semanal** (o bot inicia a conversa sozinho, sem o usuário mandar nada): confirmado por teste direto nesta sessão — `python-telegram-bot==22.8` (`requirements.txt`) expõe `telegram.ext.JobQueue`, mas essa é uma dependência **opcional** do pacote (extra `job-queue`) que precisa de `APScheduler`, **não instalado no ambiente atual** (`pip show` não lista, import falha). Adicionar isso é viável (`pip install "python-telegram-bot[job-queue]"`), mas é uma dependência nova no projeto — e mais importante: seria a **primeira vez que o bot inicia uma conversa por conta própria**. Hoje ele é 100% reativo (só responde ao que chega via `MessageHandler`); nenhum código ou documento do projeto tem precedente de mensagem proativa.

### Onde isso se encaixaria na arquitetura

- **Camada de dados**: novo tipo de Item DynamoDB (`PENDENTE#...`), no mesmo padrão de `ConfigItem` — sem `ABC`/`Protocol` novo, a não ser que surja uma segunda implementação real (mesma regra já usada para `repository/`).
- **Camada de repository**: novos métodos (ex.: `find_pending_by_user`, `resolve_pending`) — provavelmente no próprio `DynamoTransactionRepository` (já é quem decide `suspeita`/`duplicata_exata`) ou um repository-irmão dedicado, análogo a `ConfigRepository`. Decisão para o SPEC/PLN, não para agora.
- **Camada de handler**: um `CommandHandler` novo para revisão sob demanda entra sem atrito no `main.py` (mesmo padrão de registro dos três handlers existentes). Um `JobQueue` para o push semanal, se entrar em escopo, exige mudança em `main.py` (`Application.builder()` já suporta `job_queue` nativamente) e uma nova entrada na tabela de dependências do `CLAUDE.md`.

### Implicação de escopo (nova Pergunta em Aberto)

O núcleo — **persistir a pendência como Item consultável, em vez de `context.user_data`** — parece uma melhoria estrutural sobre o desenho anterior independente de quando/como o usuário revisa (resolve a perda silenciosa e a persistência de uma vez). Já a **superfície de revisão proativa e agendada** (o "check-in semanal" em si, com `JobQueue`/`APScheduler`) é um incremento de escopo maior, com uma dependência nova e um padrão de interação inédito no bot. Fica como pergunta em aberto para o SPEC decidir explicitamente, não decidida aqui.

## Relação entre os problemas

Todos decorrem da mesma lacuna estrutural: o bot é 100% stateless por design deliberado (`SPEC006`/`PATTERNS.md`, princípio "sem fluxo de pergunta-e-espera-resposta" reafirmado em pelo menos duas outras decisões do projeto — fallback de categoria e de valor ausente, `PATTERNS.md:107-118`). As três correções desta task, juntas, introduzem a primeira exceção deliberada a esse princípio.

- Problema 2 (semântica de `SUSPEITA`) e Problema 3 (falta de handler de confirmação) são consequência direta um do outro: reclassificar o hash exato — e o caso já existente de descrição similar — como "suspeita bloqueante" só funciona se o mecanismo de captura de resposta do Problema 3 existir ao mesmo tempo.
- Problema 4 (idempotência) é complementar, não substitui os Problemas 1/2 — resolve um eixo diferente (mesma entrega técnica reprocessada) que não deve ser confundido com conteúdo genuinamente distinto.
- Problema 5 depende da mesma decisão de "onde mora o estado" do Problema 3 — o Achado 2 (abaixo) aponta para um Item persistido no DynamoDB em vez de `context.user_data`; se for esse o caminho, o timestamp de chegada pode morar no mesmo Item, sem invadir `Transacao`/Entity.
- A pergunta "forçar gravação apesar do `sortKey` idêntico" (herdada do CONTEXT005) agora se aplica também ao caso de descrição similar dentro da janela de 90 dias (Problema 2), não só ao hash exato — porque ambos os casos passam a exigir confirmação e, em caso de "sim", precisam de um caminho de escrita que hoje não existe para nenhum dos dois.
- Problema 6 é uma **dimensão adicional** da já registrada "mensagens intercaladas" (Pergunta em Aberto, abaixo): não é só "mensagem nova chegando antes de confirmar a pendente", é também "a própria mensagem atual já nasce com mais de uma pendência simultânea". O Achado 2 (pendência persistida e consultável) simplifica as duas dimensões ao mesmo tempo — deixam de exigir uma máquina de estados de fila em memória.
- O achado sobre a Fase 6b (agente de conselho) e o refinamento sobre pendências persistidas + check-in (Achados 1-3) não alteram nenhum dos Problemas 1-6 em si — são restrições e oportunidades de design a levar para o SPEC/PLN, não soluções a implementar agora.

## Observações de Runtime confirmadas pelo usuário

- O bot roda como processo persistente via `polling` (`main.py`, `python-telegram-bot`), não como função serverless por mensagem.
- **Revisado nesta sessão:** a hipótese original (`context.user_data` em memória bastar para guardar a pendência) foi superada pelo Achado 2 — se a pendência precisa sobreviver a um check-in dias depois, ela precisa ser um Item persistido no DynamoDB (mesmo padrão de `ConfigItem`), não só estado em memória do processo. `context.user_data` pode ainda ter um papel (ex.: cache de leitura, ou controle de qual pendência está "em foco" numa conversa ativa), mas não deve ser a fonte de verdade da pendência em si.

## Decisões de Produto Confirmadas nesta sessão (`/map-task`)

- **Escopo:** as três correções do addendum do CONTEXT005 (idempotência via `update_id`/`message_id`, reclassificação de `SUSPEITA`, janela de tempo para calibrar a mensagem) entram **juntas** nesta mesma task — não serão fragmentadas em tasks separadas.
- **Semântica de `SUSPEITA`:** o status será reaproveitado, mas seu comportamento muda — **tanto** o caso de hash exato colidindo **quanto** o caso já existente de descrição similar dentro da janela de 90 dias passam a exigir confirmação sim/não do usuário antes de gravar. Isso substitui o comportamento atual (nota informativa, gravação imediata) por um fluxo bloqueante-até-confirmação para ambos os casos.

## Perguntas em Aberto (a resolver no SPEC/PLN)

1. **Forçar a gravação apesar do `sortKey` idêntico ou de uma similaridade encontrada**: se o usuário confirmar "sim, registra mesmo assim" (em qualquer um dos dois casos de `SUSPEITA` — hash exato ou descrição parecida), como escrever o item quando o `PutItem` condicional falharia de novo com o mesmo fingerprint? `PLN006` cogitou e descartou um sufixo de sequência para isso — precisa reabrir essa decisão com a Decisão de Produto acima como motivo concreto.
2. **Timeout de resposta, sem perda silenciosa de informação**: o que fazer se o usuário nunca responde sim/não? **Restrição confirmada pelo usuário nesta sessão: descartar a transação sem avisar é considerado um resultado ruim — perde informação financeira real sem o usuário saber.** Alternativas a explorar no SPEC: nunca expirar sozinho (fica pendente até resposta, mesmo que indefinidamente); expirar e gravar mesmo assim com uma marcação visível (ex.: categoria/nota "expirou sem confirmação, revise"); expirar e enviar uma mensagem explícita avisando que foi descartada (em vez de descartar em silêncio); ou expirar e obrigar reenvio manual. Qualquer opção escolhida precisa preservar o princípio "nunca perder dado sem que o usuário saiba".
3. **Fila de confirmação — duas dimensões, precisam de desenho conjunto**:
   - 3a. **Entre mensagens**: o usuário manda uma transação nova antes de confirmar uma pendência de uma mensagem anterior — o estado por usuário suporta só 1 pendência por vez, ou precisa de fila?
   - 3b. **Dentro da mesma mensagem** (Problema 6, novo): uma única foto/PDF/texto já produz múltiplas transações no mesmo lote, das quais só uma fração pode precisar de confirmação. Confirma-se o lote inteiro de uma vez (uma pergunta agregada), item por item em sequência, ou salva de imediato as que são `nova` e só enfileira as que precisam de confirmação?
4. **Persistência do estado — provável resolução via Achado 2, confirmar formalmente no SPEC**: modelar a pendência como Item DynamoDB (`PENDENTE#...`, mesmo padrão de `ConfigItem`) em vez de `context.user_data` resolve a sobrevivência a restart e, junto com a pergunta 2, elimina a necessidade de timeout/descarte. Falta decidir no SPEC: schema exato do Item, método(s) de repository (`find_pending_by_user`/`resolve_pending`), e se `DynamoTransactionRepository` ganha esses métodos ou se é um repository-irmão dedicado.
5. **Mecanismo de captura da resposta sim/não**: texto livre interceptado antes do `MessageHandler` de extração, ou `InlineKeyboardButton` + `CallbackQueryHandler` (handler novo, hoje inexistente no projeto)?
6. **Onde vive o timestamp de chegada da mensagem** (Problema 5): com a pendência migrando para um Item persistido (Achado 2), o timestamp provavelmente mora no mesmo Item — mas precisa ser confirmado, e decidir se ele também é necessário fora do caso de pendência (ex.: para a janela de 90 dias do Problema 2, hoje baseada só em `data` de negócio, não em hora real de chegada).
7. **Desenho da idempotência de `update_id`/`message_id`** (Problema 4): mesma lógica do Achado 2 se aplica — provavelmente também vale a pena persistir (não só em memória) para ser consistente com a garantia de "nunca perder rastro silenciosamente"; confirmar no SPEC se compartilha o mesmo Item/tabela ou é uma estrutura separada.
8. **Testes existentes que assumem o comportamento antigo de `SUSPEITA`** (`test_save_transaction_with_similar_candidate_is_suspeita`, `test_save_new_transaction_excludes_itself_from_suspeita_check`) precisam ser reescritos para refletir o novo comportamento bloqueante — confirmar no PLN o que muda em cada um.
9. **Modelagem do estado de pendência deve evitar fechar a porta para uma futura Fase 6b (agente de conselho)** — não implementar nada da Fase 6b agora (não existe, sem modelagem de dados própria, depende de Fase 6a), mas manter o estado de confirmação pendente como dado estruturado simples, não lógica hardcoded, para não precisar redesenhar do zero se uma fase futura quiser consultá-lo.
10. **Escopo da superfície de revisão de pendências** (Achado 3): o SPEC precisa decidir explicitamente se este task entrega só um comando/consulta sob demanda (`/pendencias` ou similar, sem dependência nova) ou também o push proativo semanal via `JobQueue`/`APScheduler` (dependência nova, primeiro padrão de mensagem proativa do bot) — ou se o push proativo fica como task futura separada, apoiada na mesma fundação de dados (Item `PENDENTE#`) que esta task já entregaria.

## Próximos Passos

Rota **Ambígua** (INV → SPEC → PLN → TASKS), conforme já recomendado no próprio CONTEXT005 e reforçado pelas descobertas desta sessão: a mudança reverte uma decisão de produto documentada em três lugares (`SPEC006`/`PLN006`/`TASKS006`/`PATTERNS.md`), muda o comportamento de uma funcionalidade já em produção (`SUSPEITA`), introduz o primeiro fluxo com estado de conversação do bot, e ainda acrescenta uma camada de idempotência técnica e um sinal de tempo que não existe no domínio hoje — decisões que outras funcionalidades futuras (ex. `CONTEXT003`, edição de transação) podem querer reaproveitar.
