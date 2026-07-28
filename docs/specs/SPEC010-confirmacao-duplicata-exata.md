---
type: SPEC
version: 1.2.0
author: Victor Veloso
date: 2026-07-28
status: Draft
inv: docs/analysis/INV008-confirmacao-duplicata-exata.md
---

# SPEC010 — Confirmação com estado para `DUPLICATA_EXATA` e `SUSPEITA`

## Intenção

Substituir o bloqueio automático e silencioso de `DUPLICATA_EXATA`, e o comportamento puramente informativo de `SUSPEITA`, por um único fluxo de confirmação: quando o sistema não tem certeza determinística de que uma transação é nova, ele grava uma **pendência consultável** em vez de decidir sozinho (bloquear ou salvar). O usuário resolve cada pendência com um toque (Sim/Não), na hora ou dias depois, sem nunca perder a transação candidata sem saber.

## Contexto

Ver `docs/analysis/INV008-confirmacao-duplicata-exata.md` para a investigação completa. Resumo do que motiva este SPEC:

- Hoje, `DUPLICATA_EXATA` (colisão de fingerprint `valor+tipo+descrição normalizada` no mesmo dia) bloqueia incondicionalmente e descarta a transação sem meio de forçar a gravação — mesmo quando a mensagem original do usuário era visivelmente diferente (LLM extraiu a mesma `descricao` curta de frases distintas).
- Hoje, `SUSPEITA` (descrição textualmente parecida, mesmo valor/tipo, dentro de uma janela de 90 dias) já existe mas é puramente informativo — grava a transação de imediato e só anexa uma nota na mensagem de resposta.
- Este SPEC unifica os dois: ambos os casos passam a gerar uma **pendência de confirmação**, persistida como Item no DynamoDB (mesmo padrão de `ConfigItem`), nunca em memória de processo — para sobreviver a restart e a uma revisão dias depois, sem timeout e sem descarte silencioso.
- Também entram, no mesmo escopo (decisão de produto já tomada no INV): idempotência de `update_id`/`message_id` (evitar reprocessar a mesma entrega técnica) e uma janela de tempo real de chegada da mensagem (calibrar o tom da pergunta de confirmação).
- **Fora de escopo** (decisão tomada nesta sessão): push proativo semanal (`JobQueue`/`APScheduler`) e qualquer parte da Fase 6b (agente de conselho) — ver Non-Goals.

## Requisitos (EARS)

### Idempotência de entrega (Correção 1)

- **R1.** WHEN uma mensagem recebida tiver o mesmo `update_id` (ou `message.message_id`, quando `update_id` não estiver disponível) de uma mensagem já processada para aquele usuário, o sistema SHALL descartar o reprocessamento sem chamar o LLM de extração novamente e sem gerar nenhum efeito colateral adicional (sem gravar transação, sem criar pendência).
- **R2.** O sistema SHALL considerar apenas uma janela recente de `update_id`/`message_id` processados (não uma retenção permanente) — a idempotência aqui cobre reentrega técnica de curto prazo (retry de webhook, restart no meio do processamento), não deduplicação de conteúdo (essa é a função de `DUPLICATA_EXATA`/`SUSPEITA`, tratada separadamente).

### Reclassificação de `DUPLICATA_EXATA` e `SUSPEITA` como pendência (Correção 2)

- **R3.** WHEN a extração de uma transação resultar em um `sortKey` (fingerprint exato: `data+valor+tipo+descrição normalizada`) já existente para o mesmo usuário, o sistema SHALL criar uma pendência de confirmação em vez de descartar a transação e retornar apenas um aviso.
- **R4.** WHEN a extração de uma transação encontrar, dentre as transações já confirmadas/gravadas **ou as pendências ainda abertas do mesmo usuário**, alguma com mesmo `valor`+`tipo` e descrição textualmente parecida (`is_similar`, `SIMILARITY_THRESHOLD`) dentro da janela de `SUSPECT_WINDOW_DAYS`, o sistema SHALL criar uma pendência de confirmação em vez de gravar a transação imediatamente com apenas uma nota informativa.
- **R5.** O sistema SHALL NOT gravar definitivamente uma transação candidata a pendência (R3 ou R4) até que o usuário a confirme explicitamente.
- **R6.** Comportamento diferente para cada tipo de checagem, por causa de uma propriedade matemática:
  - Para fins de **R3** (fingerprint exato), o sistema SHALL comparar apenas contra transações já confirmadas/gravadas — **não** precisa incluir pendências abertas na busca, porque igualdade de fingerprint é transitiva: qualquer transação nova cujo fingerprint seja idêntico ao de uma pendência aberta necessariamente também tem fingerprint idêntico à transação original confirmada que gerou aquela pendência (o fingerprint é um hash determinístico de `valor+tipo+descrição normalizada` — se dois itens têm fingerprints iguais a um terceiro, os três são iguais entre si). Ou seja, o R3 já pega esse caso sozinho, sem precisar olhar pendências.
  - Para fins de **R4** (similaridade textual), o sistema SHALL incluir as pendências abertas do mesmo usuário na busca (ver R4 acima) — **obrigatório**, porque `is_similar` (`SequenceMatcher`) **não é transitivo**: uma transação nova pode ser praticamente idêntica a uma pendência aberta e, ainda assim, não atingir o limiar de similaridade contra a transação original confirmada que gerou aquela pendência (basta a pendência já estar na borda do limiar). Sem incluir a pendência na busca, esse duplicado passaria como `nova` sem nenhum aviso — silenciosamente contando duas vezes no saldo. Incluir pendências na busca fecha esse furo.
  - **Consequência aceita** (redundância, não perda de dado): quando uma transação nova bate com uma pendência aberta (R4 ampliado), ela também vira uma pendência própria, possivelmente duplicando a necessidade de confirmação (o usuário resolve duas pendências parecidas em vez de uma). Isso é fricção de UX aceita, não um defeito — o que importa é que nada é gravado como `nova` sem checagem.

### Persistência da pendência

- **R7.** O sistema SHALL persistir cada pendência de confirmação como um Item na mesma tabela DynamoDB das transações (mesmo padrão de `ConfigItem`, sem tabela nova), contendo: os dados completos da transação candidata, o motivo (`duplicata_exata` ou `suspeita`), a(s) transação(ões) similar(es) encontrada(s) quando houver, e o timestamp real de chegada da mensagem que a originou (Correção 3).
- **R8.** Uma pendência de confirmação SHALL permanecer no estado "pendente" indefinidamente até o usuário respondê-la explicitamente. O sistema SHALL NOT expirar ou descartar automaticamente uma pendência por decurso de tempo.
- **R9.** Uma pendência de confirmação SHALL sobreviver a um restart do processo do bot (por ser um Item persistido, não estado em memória).

### Fluxo do usuário (não bloqueante)

- **R10.** WHILE existir(em) pendência(s) de confirmação em aberto para um usuário, o sistema SHALL continuar processando normalmente as novas mensagens desse usuário (extração e gravação imediata de transações classificadas como `nova`) — pendências em aberto SHALL NOT bloquear o uso do bot.
- **R11.** WHEN uma única mensagem (texto, foto ou PDF) produzir múltiplas transações, o sistema SHALL processar cada uma independentemente: gravar de imediato as que forem `nova`, e criar uma pendência separada para cada uma que for `suspeita`/`duplicata_exata` — sem exigir que o usuário resolva todas as pendências do lote de uma vez, nem bloquear o restante do lote.
- **R12.** WHEN uma pendência de confirmação for criada (R3/R4), a própria mensagem de resposta do bot para aquela transação SHALL incluir imediatamente os botões inline "Sim"/"Não" — o usuário pode resolver ali mesmo, sem precisar de nenhum comando adicional.
- **R13.** WHEN o usuário invocar o comando de consulta de pendências, o sistema SHALL listar todas as pendências em aberto daquele usuário (incluindo as que já apareceram antes via R12 e ainda não foram respondidas), cada uma exibindo os dados da transação candidata e (quando houver) da transação similar encontrada, com botões inline "Sim"/"Não" funcionais para resolução individual.
- **R14.** O sistema SHALL usar `InlineKeyboardButton` + `CallbackQueryHandler` para capturar a resposta de confirmação (tanto em R12 quanto em R13) — não texto livre.
- **R15.** WHEN o usuário tocar "Sim" numa pendência, o sistema SHALL gravar a transação correspondente definitivamente — mesmo que o fingerprint colida com o item já existente que originou a pendência — e remover a pendência da lista de pendentes.
- **R16.** WHEN o usuário tocar "Não" numa pendência, o sistema SHALL descartar a transação candidata, remover a pendência da lista de pendentes, e confirmar ao usuário (na própria interação) que a transação foi descartada por decisão explícita dele — isso não é descarte silencioso, é decisão informada.

### Calibração por janela de tempo (Correção 3)

- **R17.** WHEN o sistema apresentar uma pendência de confirmação (via R12 ou R13), o texto SHALL ser calibrado pelo intervalo entre o timestamp de chegada da mensagem candidata e o timestamp de chegada da transação original que ela colide/se parece: intervalos curtos (poucos segundos a poucos minutos) SHALL usar um texto que sugere duplo-envio acidental; intervalos maiores (minutos/horas ou mais) SHALL usar um texto neutro, sem presumir duplicidade.

## Non-Goals

- **Não implementa push proativo semanal** (o bot iniciar a conversa sozinho via `JobQueue`/`APScheduler`) — fica como task futura, apoiada na mesma fundação de dados (Item de pendência) que este SPEC entrega. Não adicionar a dependência `APScheduler` nesta task.
- **Não implementa nenhuma parte da Fase 6b** (agente de conselho) — a única obrigação aqui é não desenhar a pendência de um jeito que impeça uma fase futura de consultá-la (dado estruturado simples, não lógica hardcoded no handler).
- **Não altera `models.Transacao` (DTO)** para incluir timestamp de chegada — o timestamp vive só na estrutura da pendência (Item de dedup), não no domínio de transação.
- **Não implementa fila com bloqueio** de mensagens intercaladas — resolvido por R9: pendências coexistem livremente, sem travar o fluxo principal.
- **Não migra pendências antigas** nem dados históricos — este SPEC vale só para transações processadas a partir da implementação.
- **Não trata timeout de resposta como descarte automático** — R7 fixa que não há expiração automática; não há "prazo" a configurar.

## Critérios de Aceitação

1. Reenviar uma transação com conteúdo genuinamente diferente, mas que o LLM extraiu para o mesmo fingerprint do mesmo dia, gera uma pendência — não é bloqueada nem descartada silenciosamente.
2. Duas transações com descrição textualmente parecida (mesmo valor/tipo) dentro da janela de 90 dias geram uma pendência — não são mais gravadas de imediato com apenas uma nota informativa.
3. O comando de consulta de pendências lista todas as pendências em aberto do usuário, cada uma com botões "Sim"/"Não".
4. Confirmar "Sim" grava a transação definitivamente (mesmo com fingerprint colidindo) e a remove da lista de pendentes.
5. Confirmar "Não" descarta a transação, remove a pendência, e o usuário recebe confirmação explícita do descarte.
6. Reenvio do mesmo `update_id`/`message_id` não dispara nova chamada ao LLM nem gera pendência duplicada.
7. Uma foto/PDF que produz N transações, das quais uma fração é `suspeita`/`duplicata_exata`, grava de imediato as que são `nova` e cria uma pendência por item que precisa de confirmação — sem bloquear o restante do lote.
8. Reiniciar o processo do bot não apaga pendências em aberto — elas continuam listadas no comando de consulta depois do restart.
9. Nenhuma pendência expira ou é descartada automaticamente por decurso de tempo — só sai do estado pendente por ação explícita do usuário (Sim ou Não).
10. O texto de uma pendência cujo intervalo entre timestamps é curto (segundos/poucos minutos) difere visivelmente do texto de uma pendência com intervalo longo (minutos/horas ou mais).
11. Nenhuma dependência nova (`APScheduler`) é adicionada ao projeto por esta task.
12. Ao criar uma pendência, a mensagem de resposta à transação que a originou já vem com os botões "Sim"/"Não" — o usuário não precisa rodar nenhum comando para resolver na hora, se quiser.
13. Enviar uma transação parecida (por fingerprint exato ou por similaridade textual) antes de resolver uma pendência anterior gera uma segunda pendência — nunca é salva como `nova` sem checagem, mesmo quando não bate o suficiente com a transação original confirmada, só com a pendência ainda aberta.
14. Ignorar os botões de uma pendência e enviar outra transação (nova ou não) não afeta a pendência em aberto — ela continua listada e resolvível normalmente depois, via os botões originais ou via o comando de consulta.
