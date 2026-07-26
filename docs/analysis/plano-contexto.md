# Plano de Migração — Guardião Financeiro (monólito EC2 → serverless AWS)

> Documento de contexto para implementação junto ao Claude Code.
> O template CloudFormation existente (`guardiao-financeiro-stack.yaml`) é o **alinhamento arquitetural do alvo**, não um deploy literal. A migração acontece em fases pequenas, cada uma deixando o bot funcionando ao final.

---

## 1. Estado atual (o que já funciona)

```
┌────────────────────────── EC2 (processo único, 24/7) ──────────────────────────┐
│                                                                                │
│  main.py ── run_polling() ──► python-telegram-bot (long polling)               │
│                                      │                                         │
│              ┌───────────────────────┼───────────────────────┐                 │
│              ▼                       ▼                       ▼                 │
│      text_handler.py         photo_handler.py         pdf_handler.py           │
│              │                       │                       │                 │
│              └───────────► services/ (lógica pura) ◄─────────┘                 │
│                                      │                                         │
│                    ┌─────────────────┼──────────────────┐                      │
│                    ▼                 ▼                  ▼                      │
│             google-genai      pasta local fotos/   repository/                 │
│           (gemini-2.5-flash)   (armazenamento       │                          │
│            texto + OCR          temporário)         ▼                          │
│                                              SQLAlchemy async                  │
│                                              + SQLite (aiosqlite)              │
└────────────────────────────────────────────────────────────────────────────────┘
```

Pontos fortes a preservar:
- Camadas limpas: handler → service → repository (nunca handler → repository)
- `Transacao` (Pydantic) como DTO de domínio — o contrato que atravessa as camadas
- Deduplicação determinística de 3 estados (NOVA / SUSPEITA / DUPLICATA EXATA), sem IA
- Regras do agente em arquivo estilo CLAUDE.md editável

Limitações que motivam a migração:
- Processo 24/7 em EC2 (custo fixo, ponto único de falha)
- Gemini como dependência externa fora do ecossistema AWS
- SQLite local (sem durabilidade gerenciada, não escala, preso ao disco da EC2)
- Arquivos em disco local (`fotos/`)
- Sem fluxo de consulta ainda (só registro)

---

## 2. Estado alvo (alinhado ao CloudFormation)

```
Telegram ──POST──► API Gateway (HTTP API, rota /webhook)
                        │  valida X-Telegram-Bot-Api-Secret-Token
                        ▼
                Lambda Receptora (fina: parse, dedup de update_id, StartExecution)
                        │
                        ▼
        ┌──────────── Step Functions: Fluxo-GuardiaoFinanceiro ────────────┐
        │                                                                  │
        │  Valida tipo ──► Escolha ──┬── TXT ──► Bedrock Nova Micro        │
        │  (Lambda)         │        │           (transação ou consulta?)  │
        │                   │        │                 │                   │
        │             Default: Fail  │        ┌────────┴────────┐          │
        │                            │        ▼                 ▼          │
        │                            │    [consulta]       [transação]     │
        │                            │   Query DynamoDB   Verifica dup     │
        │                            │        │           PutItem Dynamo   │
        │                            │        ▼                 │          │
        │                            │   Lambda formata         │          │
        │                            │        │                 │          │
        │                            └── ARQ ─┤                 │          │
        │                                     ▼                 │          │
        │                            PutObject S3               │          │
        │                                     │                 │          │
        │                            Bedrock Nova Lite (OCR)    │          │
        │                                     │                 │          │
        │                            Extrai transação ──► dup ──┤          │
        │                                     │                 │          │
        │                            DeleteObject S3            │          │
        │                                     └────────┬────────┘          │
        │                                              ▼                   │
        │                                    Responder Telegram            │
        │                                    (Lambda sendMessage)          │
        │                                                                  │
        │  Catch em todos os Tasks ──► Notifica erro ao usuário + log      │
        └──────────────────────────────────────────────────────────────────┘

        DynamoDB: PK userId | SK timestamp#transactionId | GSI categoria
        S3: lifecycle rule expira objetos em 1 dia (rede de segurança do Delete)
```

Diferenças em relação ao diagrama original do Step Functions (melhorias incorporadas):
1. **`Default` + estado `Fail`** na primeira Choice (o original travava silenciosamente se `tipo` não fosse TXT nem ARQ).
2. **Estado "Verifica Duplicata"** antes de todo PutItem — a dedup de 3 estados do bot atual estava ausente do desenho.
3. **Estado final "Responder Telegram"** — o original terminava num "Lambda Invoke" genérico sem fechar o ciclo com o usuário.
4. **`Catch` nos Tasks** direcionando para um estado de erro que avisa o usuário ("não consegui processar, tenta de novo") em vez de falhar mudo.
5. **Consulta usa `Query`** (userId + faixa de data/categoria), não `GetItem` por chave exata.
6. **Dois modelos Bedrock**: Nova Micro (texto puro, mais barato) e Nova Lite (OCR, degrau multimodal mais barato) — estratégia de custo: IA só em pontos estratégicos, sem overkill.

---

## 3. Princípios da migração

1. **Uma mudança de infraestrutura por fase.** Nunca trocar LLM e banco na mesma fase.
2. **O bot funciona ao final de cada fase.** Cada fase termina com o bot em produção respondendo mensagens reais.
3. **Rollback sempre possível.** Toda troca de provedor/serviço fica atrás de flag de ambiente até a fase seguinte confirmar estabilidade.
4. **A lógica de negócio não se move.** Dedup, `Transacao`, validação de saída do LLM — tudo em `services/` permanece intacto. Só as bordas (LLM, storage, banco, listener) mudam.
5. **Dependência dita ordem** ("não dá pra abrir o navegador com o PC desligado"):
   - Tudo AWS depende da Fase 0 (credenciais + acesso aos modelos).
   - Decompor em Lambdas depende de dados e arquivos já estarem na nuvem (Lambda não tem disco persistente nem SQLite compartilhado).
   - Step Functions depende das Lambdas existirem.
   - Webhook depende de ter algo serverless para invocar.

---

## 4. Fases

### Fase 0 — Fundação AWS (o "ligar o PC")

Nada de código do bot muda. Só preparar o terreno.

- Definir região única para tudo (atenção: os ARNs do template usam `us-east-2` para Bedrock — confirmar em qual região Nova Micro/Lite estão disponíveis e fixar).
- Criar IAM user/role de desenvolvimento com política mínima: `bedrock:InvokeModel` nos dois modelos, e depois incrementar por fase (S3 na Fase 2, DynamoDB na Fase 3...). Não criar um admin genérico.
- Habilitar o acesso aos modelos Nova Micro e Nova Lite no console do Bedrock (model access é opt-in por conta/região).
- Instalar `boto3`, configurar credenciais na EC2 (idealmente via instance profile/role, não access key em `.env`).
- Smoke test fora do bot: um script avulso que invoca Nova Micro com "olá" e Nova Lite com uma imagem, confirmando resposta.

**Critério de saída:** os dois modelos respondem a partir da EC2.

### Fase 1 — Trocar Gemini por Bedrock (dentro do monólito)

O bot continua monólito, polling, SQLite, disco local. Só o cérebro muda.

- **1.1 Criar a abstração de provedor de LLM.** Hoje os services chamam `google-genai` direto (ou perto disso). Introduzir uma interface (`LLMProvider` ou similar) com dois contratos: `extrair_transacao_de_texto(texto) -> Transacao` e `extrair_transacao_de_imagem(bytes, mime) -> Transacao`. Os services passam a depender da interface, nunca do SDK. Isso é o investimento que torna esta e qualquer futura troca barata.
- **1.2 Implementar `GeminiProvider`** apenas movendo o código existente para dentro da interface (refactor sem mudança de comportamento — dá pra validar que nada quebrou antes de introduzir o Bedrock).
- **1.3 Implementar `BedrockProvider`** usando a Converse API do boto3: Nova Micro para texto, Nova Lite para imagem/PDF. Adaptar `prompts.py` mantendo os prompts como fonte única (o provider formata para o wire format de cada API).
- **1.4 Validação de saída continua obrigatória.** A saída do modelo passa pelo mesmo parse/validação Pydantic antes de virar `Transacao` — nunca confiar em texto de LLM para dado financeiro. Saída malformada = erro tratado, não exceção vazando pro usuário.
- **1.5 Flag de ambiente `LLM_PROVIDER=gemini|bedrock`** para alternar em runtime. Rodar alguns dias em `bedrock` com possibilidade de voltar.
- **1.6 Tratamento de erros específico do Bedrock:**
  - `ThrottlingException` → retry com backoff exponencial + jitter (máx. 3 tentativas), espelhando a política de Retry do state machine.
  - `ValidationException` / payload rejeitado → log detalhado + mensagem amigável ao usuário.
  - Timeout de rede → mesmo tratamento de retry.
  - Resposta vazia ou JSON inválido do modelo → uma re-tentativa com o mesmo prompt; persistindo, informar o usuário que não conseguiu entender.
- **1.7 Limpeza:** removido o `GeminiProvider` e a `GEMINI_API_KEY` só na fase seguinte, depois de estabilidade confirmada.

**Critério de saída:** bot em produção extraindo transações de TXT, foto e PDF via Bedrock, com Gemini removível a qualquer momento.

**Risco conhecido:** Nova Micro/Lite podem errar mais que Gemini 2.5 Flash em casos ambíguos (recibo mal formatado, texto solto). Monitorar taxa de saída malformada; se ficar alta, considerar fallback pontual: Micro falhou na validação → repetir no Lite, sem pagar o modelo maior no volume todo.

### Fase 2 — Arquivos: `fotos/` local → S3

Ainda monólito. Muda só onde o arquivo temporário vive.

- Criar o bucket (nome e políticas conforme o template: private, criptografado).
- **Lifecycle rule: expirar objetos com 1 dia.** Essa é a rede de segurança — se o delete pós-processamento falhar, nada fica órfão pagando storage.
- Fluxo: recebeu foto/PDF → upload para S3 (`{userId}/{timestamp}-{file_id}`) → processa (o provider Bedrock pode receber os bytes direto; o S3 aqui é durabilidade durante o processamento e preparação para o desenho futuro, onde o OCR lê do S3) → deletar objeto após extração confirmada.
- Erros: falha de upload → responder ao usuário e abortar (não processar arquivo que não persistiu); falha de delete → logar e seguir (lifecycle resolve); arquivo acima de um limite de tamanho → recusar com mensagem clara antes de qualquer upload.
- Remover `os.makedirs("fotos")` e toda escrita em disco local.

**Critério de saída:** nenhum arquivo toca o disco da EC2; S3 esvazia sozinho.

### Fase 3 — Dados: SQLite → DynamoDB

A fase mais delicada, porque toca a dedup. Ainda monólito.

- Criar a tabela conforme o template: PK `userId` (S), SK `sortKey` = `{timestamp ISO}#{transactionId}` (S), GSI `userId`+`categoria`. `PAY_PER_REQUEST`.
- **Reescrever apenas `repository/`** — este é o payoff da arquitetura em camadas. Services e handlers não devem mudar (se precisarem, é sinal de vazamento de abstração a corrigir antes).
- **Redesenhar a dedup para chave-valor:**
  - DUPLICATA EXATA → idempotência nativa: `PutItem` com `ConditionExpression: attribute_not_exists(sortKey)` sobre uma chave determinística derivada dos campos da transação. `ConditionalCheckFailedException` = duplicata exata, sem query prévia.
  - SUSPEITA → `Query` por `userId` + faixa de `sortKey` (janela de data) e comparação em memória com a mesma regra determinística de hoje. A regra não muda; muda só de onde vêm os candidatos.
  - Documentar essa decisão em `docs/decisoes-arquiteturais.md` como as demais.
- Script one-shot de migração SQLite → DynamoDB dos dados existentes (rodar, conferir contagens, guardar o .db como backup).
- Flag `DB_BACKEND=sqlite|dynamo` durante a transição, mesmo padrão da Fase 1.
- Erros: `ProvisionedThroughputExceeded`/throttling → retry com backoff; `ConditionalCheckFailed` → não é erro, é o sinal de duplicata (fluxo normal); falha de rede no meio de operação → como cada transação é um único `PutItem`, não há estado parcial a limpar.

**Critério de saída:** SQLite desligado, dedup funcionando igual (mesmos 3 estados, mesmos resultados nos mesmos casos de teste), dados históricos migrados.

### Fase 4 — Listener: polling → webhook + Lambda

Agora sim o monólito pode ser desmontado, porque nada mais depende do disco/processo da EC2.

- **4.1 Empacotar o core como uma Lambda "processadora"** (lift-and-shift: uma função que recebe o update do Telegram e executa o mesmo caminho handler→service→repository de hoje). Atenção aos ajustes de fronteira: os handlers atuais recebem `Update` do python-telegram-bot; a Lambda recebe o JSON cru do webhook — criar um adaptador fino de parse (a lib pode continuar sendo usada só para `de_json` e para chamar a API de envio).
- **4.2 API Gateway (HTTP API)** com rota `POST /webhook` → Lambda receptora.
- **4.3 Lambda receptora fina** (sem lógica de negócio):
  - Valida o header `X-Telegram-Bot-Api-Secret-Token` (rejeita 403 sem ele).
  - **Idempotência por `update_id`:** o Telegram reenvia updates se não receber 200 rápido. Registrar `update_id` processados (item DynamoDB com TTL curto) e ignorar repetidos — sem isso, transações duplicadas vão nascer do próprio transporte.
  - Responde **200 imediatamente** e invoca a processadora de forma assíncrona (invoke `Event`). Nunca processar sincronamente dentro do timeout do webhook.
- **4.4 DLQ (SQS) na invocação assíncrona** da processadora: falhas após retries caem na fila para inspeção, em vez de sumirem.
- **4.5 Registrar o webhook** (`setWebhook` com a URL do API Gateway + secret token) e desligar o `run_polling`. A EC2 continua existindo só como fallback até a Fase 5.
- Erros: assinatura inválida → 403 e log; payload não reconhecido → 200 (para o Telegram parar de reenviar) + log; processadora estourando timeout → ajustar memória/timeout e monitorar.

**Critério de saída:** bot 100% event-driven, EC2 ociosa (pode parar a instância e o bot continua funcionando).

### Fase 5 — Step Functions: orquestração explícita

Quebrar a Lambda processadora nos states do desenho alvo.

- Extrair da processadora as etapas que viram **states nativos** (Bedrock InvokeModel, DynamoDB PutItem/Query, S3 Put/Delete) e as que continuam **Lambdas** (validação/classificação de tipo, normalização pós-LLM, formatação de resposta, envio ao Telegram).
- A Lambda receptora troca o invoke assíncrono por `states:StartExecution`.
- Implementar o state machine com as 6 melhorias da seção 2 (Default/Fail, dedup state, Responder Telegram, Catch global, Query na consulta, dois modelos).
- `Catch` em cada Task → estado "Notifica Erro" (mensagem ao usuário + log estruturado). Execução nunca termina em falha silenciosa.
- Padrões de Retry idênticos aos já definidos no template (backoff 2x, jitter FULL, 3 tentativas).
- Só aqui o CloudFormation vira deploy de verdade: evoluir o template para incluir API Gateway, Lambdas, DLQ e a EventBridge Connection do `http:invoke` (pendência conhecida do template), e passar a deployar por ele (ou converter para SAM, decisão a tomar nesta fase).
- Desligar a EC2 definitivamente.

**Critério de saída:** cada mensagem gera uma execução visível no console do Step Functions, com trilha completa de auditoria por transação.

### Fase 6 — Fluxo de consulta (feature nova sobre a fundação pronta)

Intencionalmente por último: construir consulta antes da Fase 3 significaria escrevê-la duas vezes (SQL e depois DynamoDB).

- Classificação transação × consulta no state do Nova Micro (o `isTransaction` do desenho).
- Consulta: Nova Micro interpreta a pergunta → extrai filtros estruturados (período, categoria) → `Query` na tabela/GSI → Lambda agrega e formata → resposta. Mantém a decisão antiga: function calling + agregação, **não RAG**.
- Ramo futuro de "conselhos financeiros" (objetivo do produto) entra depois, sobre o mesmo mecanismo de consulta.

---

## 5. Mapa de dependências (por que esta ordem)

```
Fase 0 (credenciais + model access)
  └─► Fase 1 (Bedrock)          ── independente de 2 e 3
  └─► Fase 2 (S3)               ── independente de 1 e 3
  └─► Fase 3 (DynamoDB)         ── independente de 1 e 2
            │
            ▼  (Lambda exige dados e arquivos fora do disco local → 2 e 3 prontas)
        Fase 4 (webhook + Lambdas)
            │
            ▼  (orquestrar exige as peças serverless existirem)
        Fase 5 (Step Functions)
            │
            ▼  (consulta usa DynamoDB + orquestração prontas)
        Fase 6 (consultas)
```

1, 2 e 3 são tecnicamente paralelizáveis, mas a ordem 1→2→3 mantém uma mudança por vez, começando pela troca de menor risco estrutural (LLM é a borda mais isolada; banco é a mais entranhada).

---

## 6. Lista de tarefas (para o Claude Code)

### Fase 0 — Fundação
- [ ] Definir e fixar a região AWS (verificar disponibilidade de Nova Micro/Lite)
- [ ] Criar IAM role/user mínimo (só `bedrock:InvokeModel` nos 2 ARNs por enquanto)
- [ ] Habilitar model access de Nova Micro e Nova Lite no console Bedrock
- [ ] Configurar credenciais na EC2 via instance profile
- [ ] Script de smoke test invocando os dois modelos

### Fase 1 — Gemini → Bedrock
- [ ] Criar interface `LLMProvider` (texto e imagem) consumida pelos services
- [ ] Refatorar código Gemini existente para `GeminiProvider` (sem mudança de comportamento)
- [ ] Implementar `BedrockProvider` (Converse API: Nova Micro texto, Nova Lite imagem/PDF)
- [ ] Adaptar `prompts.py` para servir os dois providers a partir de fonte única
- [ ] Garantir validação Pydantic da saída do LLM em ambos os providers
- [ ] Flag `LLM_PROVIDER` para alternância em runtime
- [ ] Retry com backoff+jitter para throttling/timeout do Bedrock
- [ ] Tratamento de saída malformada (1 re-tentativa → mensagem amigável)
- [ ] Rodar em produção com `bedrock` e monitorar taxa de erro de extração
- [ ] (pós-estabilidade) Remover google-genai e GEMINI_API_KEY

### Fase 2 — fotos/ → S3
- [ ] Criar bucket privado criptografado + lifecycle de 1 dia
- [ ] Ampliar IAM: s3 Put/Get/Delete no bucket
- [ ] Trocar escrita local por upload S3 com chave `{userId}/{timestamp}-{file_id}`
- [ ] Delete pós-extração (falha de delete = log, não bloqueio)
- [ ] Limite de tamanho de arquivo com recusa amigável
- [ ] Remover pasta fotos/ e makedirs

### Fase 3 — SQLite → DynamoDB
- [ ] Criar tabela (PK userId, SK timestamp#transactionId, GSI categoria, on-demand)
- [ ] Ampliar IAM: GetItem/PutItem/Query na tabela e índices
- [ ] Reimplementar repository/ para DynamoDB (services intocados)
- [ ] Dedup: DUPLICATA EXATA via ConditionExpression em chave determinística
- [ ] Dedup: SUSPEITA via Query por janela de data + regra determinística atual
- [ ] Testes de dedup comparando resultados SQLite × DynamoDB nos mesmos casos
- [ ] Script one-shot de migração de dados + conferência de contagens
- [ ] Flag `DB_BACKEND` durante a transição
- [ ] Documentar decisão em docs/decisoes-arquiteturais.md
- [ ] (pós-estabilidade) Desligar SQLite

### Fase 4 — polling → webhook
- [ ] Adaptador de parse: JSON cru do webhook → objetos internos (Update.de_json)
- [ ] Empacotar core como Lambda processadora (invocação assíncrona)
- [ ] API Gateway HTTP API com rota POST /webhook
- [ ] Lambda receptora: validação do secret token (403 se ausente/errado)
- [ ] Idempotência por update_id (DynamoDB com TTL)
- [ ] DLQ (SQS) para falhas da processadora
- [ ] setWebhook com secret token; desligar run_polling
- [ ] EC2 parada como validação (bot segue de pé)

### Fase 5 — Step Functions
- [ ] Separar states nativos (Bedrock/DynamoDB/S3) de Lambdas (validação, normalização, resposta)
- [ ] Implementar state machine com: Default+Fail na Choice, state de dedup, state Responder Telegram, Catch→Notifica Erro em todos os Tasks
- [ ] Receptora passa a chamar StartExecution
- [ ] Evoluir o CloudFormation para deploy real (incluir API GW, Lambdas, DLQ, EventBridge Connection) ou decidir migração para SAM
- [ ] Desligar EC2 definitivamente

### Fase 6 — Consultas
- [ ] Classificação transação × consulta no prompt do Nova Micro
- [ ] Extração de filtros estruturados (período, categoria) da pergunta
- [ ] Query/agregação na tabela e GSI + formatação de resposta
- [ ] (futuro) Ramo de conselhos financeiros sobre o mecanismo de consulta