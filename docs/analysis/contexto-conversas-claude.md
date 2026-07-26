# Contexto histórico — Guardião Financeiro (por conversa)

> Consolidação de tudo que foi discutido e decidido sobre o bot, em ordem cronológica.
> Complementa o `plano-migracao-guardiao-financeiro.md`. Marcações: **[decisão]** = escolha feita por Veloso; **[design]** = raciocínio arquitetural acordado; **[sugestão]** = proposta do assistente ainda não confirmada como decisão.

---

## 1. Nascimento do projeto — "Bot Telegram com Python básico" (~28/06/2026)

Sessão que construiu o bot do zero até a arquitetura em camadas.

- Projeto em `~/dev/side-projects/guardiao_financeiro_python/`, Python 3.12 + venv.
- Bot criado via BotFather; `python-telegram-bot` 22.8 (async); config via `.env` + `python-dotenv` com `config.py` centralizando variáveis.
- Handlers de foto (`filters.PHOTO`) e PDF (`filters.Document.PDF`); Gemini (`gemini-2.5-flash`) via SDK atual `google-genai` (não o deprecado `google-generativeai`) para OCR de extratos.
- `format_service.py` para respostas HTML com chunking (limite de 4096 caracteres do Telegram); `nlp_service.py` para entrada de transação em texto livre; allowlist de user IDs em `auth_service.py`.
- Estrutura `handlers/` + `services/` espelhando a separação controller/service do NestJS (background do Veloso).
- **[decisão]** RabbitMQ descartado: escala pessoal (1-2 usuários, volume semanal/mensal) não justifica.
- **[decisão]** LangChain adiado até RAG ou orquestração multi-step serem genuinamente necessários.
- **[decisão]** Sem camada de API intermediária entre bot e banco enquanto um único processo Python for dono dos dados.
- **[decisão]** SQLite como primeiro passo de persistência.
- **[design]** Objetivo real não é só OCR: sistema de inteligência financeira onde o usuário pergunta "posso comprar X?" / "quanto posso gastar sem comprometer?" — via **function calling + agregação SQL, não RAG** (o RAG foi inicialmente confundido com o caso de uso e descartado explicitamente).
- Bedrock já apareceu aqui como alternativa possível ao free tier do Gemini (explorado, não decidido na época).

## 2. Fundação de dados e dedup — "Arquitetura de bot Telegram com Gemini" (28/06/2026)

A conversa que definiu o coração do bot: a deduplicação.

- Implementada a fundação SQLAlchemy 2.0 async + aiosqlite (`database/connection.py`, `database/entities.py`); nenhum handler alterado — "só a fundação existindo".
- **[design]** Taxonomia dos 4 tipos de duplicidade que o fluxo pode gerar:
  1. Reenvio do arquivo idêntico → resolvido com **hash dos bytes crus antes de chamar o LLM** (bônus: economiza a chamada de API).
  2. Sobreposição de período (extrato 1–15/jan + extrato 10–31/jan) → hash não pega; exige comparar transações extraídas contra o histórico.
  3. Transação real repetida vs. duplicata (dois cafés de R$8 no mesmo dia são legítimos) → regra ingênua de data+valor+descrição **apagaria transações reais**, que é pior do que deixar duplicata passar.
  4. Ruído do OCR (mesma transação com variações de texto) → exige normalização/comparação aproximada, não igualdade de string.
- **[design]** Camadas de defesa: hash de arquivo (camada 0) → assinatura da transação (data + valor + tipo + descrição normalizada, comparada contra janela de 60–90 dias do mesmo usuário) → classificação em 3 estados **NOVA / SUSPEITA / DUPLICATA EXATA** em vez de decisão binária.
- **[decisão]** Dedup 100% determinística, **sem IA na comparação** — motivos: dado financeiro não admite não-determinismo, testabilidade com asserts simples, custo/latência de chamada extra de LLM por transação.
- **[design]** Fluxo canônico: mensagem → service de IA extrai (DTO `Transacao`, ainda não salvo) → service de dedup determinístico classifica → só então insere / bloqueia / pergunta ao usuário.
- **[design]** Flask/FastAPI: sem função no desenho atual (polling = nenhum servidor HTTP recebendo requisição). Entrariam apenas num cenário de webhook — que é exatamente a Fase 4 do plano atual.

## 3. Bot como portfólio — "Preparação para entrevista full stack" (01/07/2026)

Tangencial, mas define o "porquê" de vários rigores do projeto.

- O bot foi identificado como o **diferencial mais forte do portfólio para audiência fintech**: demonstra raciocínio sobre problemas específicos do domínio — idempotência, dedup determinística de 3 estados, **validação da saída do LLM antes de confiar em dado financeiro**, e linguagem natural → SQL como feature de estado final.
- Implicação prática: essas propriedades são inegociáveis na migração — são o argumento do projeto, não detalhes.

## 4. Menção lateral — "Frontend app para treinar LangChain" (04/07/2026)

- Uma das opções levantadas foi estender o Guardião com agents/tools do LangChain. **[sugestão]** não levada adiante; a decisão anterior (LangChain só quando necessário) permanece.

## 5. Deploy no protótipo — "EC2 para bot Python é overkill?" (16/07/2026)

Estado de produção atual, relevante como ponto de partida da migração.

- t3.micro (novo free tier pós-jul/2025, por créditos); custo zero confirmado em teste overnight.
- Security group: só SSH/22 restrito a "My IP"; nada de porta de entrada para o bot (polling não recebe conexão).
- Deploy via git clone (PAT ou Deploy Key); `.env` criado manualmente na instância, fora do repo.
- systemd service `guardiao-bot.service` com `Restart=always` + `EnvironmentFile`; `systemctl enable` para boot automático; script de deploy = `git pull` + `pip install` + `restart`.
- IP público muda a cada stop/start (afeta só SSH); alertas de billing configurados como precaução.

## 6. Produto e fluxo de consulta — "Bot Telegram para gestão financeira com Gemini" (18/07/2026)

A conversa que formalizou o objetivo de produto e abriu o design de consultas.

- **[decisão]** Objetivo do produto: **substituir o Guardião Financeiro atual do Veloso (Claude Cowork + conexão Notion)**. Duas funcionalidades principais: registrar transações (texto/imagem/PDF) e dar conselhos financeiros ("consigo comprar X sem comprometer?", "quanto posso gastar com lazer nesse fds?").
- **[decisão]** Regras de comportamento do agente ficam num arquivo estilo CLAUDE.md **editável pelo usuário** (espelhando o agente atual do Cowork).
- A conexão com o Notion foi consultada: hub do Guardião com "Situação atual", os 5 baldes, tabela do Serasa, Controle de Gastos 2026 e a Base — é a estrutura que o bot substitui.
- Regras de engenharia do CLAUDE.md do repo (vigentes): lógica de negócio nunca em `handlers/` (só orquestração); Gemini só chamado de `ocr_service.py`/`nlp_service.py`; nunca fundir `Transacao` (DTO) com `TransacaoEntity` (SQLAlchemy); commit em lote, nunca dentro de loop; **não adicionar Protocol/ABC ao repository sem uma segunda implementação real** (nota: a Fase 1 do plano de migração cria a segunda implementação real do provider de LLM — a condição para a abstração passa a existir); `TRANSACTION_SCHEMA` importado de `prompts.py` em todo ponto de entrada que chame o LLM.
- Fluxo de trabalho SDD: `/map-task` → `/clear` → `/start-task docs/tasks/TASKSXXX-slug.md`, com leitura obrigatória de CLAUDE.md e `docs/PATTERNS.md` antes de tocar código.
- **[design]** Para consultas: roteamento de intenção vem antes de tudo — o `text_handler` de hoje assume que toda mensagem é registro; passa a distinguir "gastei 50 no ifood" (registro) de "quanto gastei com delivery esse mês?" (consulta) de "posso comprar um fone de 200?" (conselho).

## 7. Segurança e modelos — "Migração do Guardião Financeiro para AWS" (20/07/2026)

Revisão de uma conversa prévia do Veloso no Google AI Mode (via screenshot).

- Esclarecido papel das ferramentas AWS: EMR (processamento pesado Spark/Hadoop — fora de escopo), Step Functions (orquestração — o caminho), Glue/Hop (ETL — fora de escopo).
- Correções ao ASL rascunhado no AI Mode: `getAgent` usado incorretamente no lugar de `invokeModel`/`invokeAgent`, ARNs faltando, problemas de sintaxe JSONata.
- **[decisão]** Arquitetura de segurança **rígida** para sistema financeiro: cada componente de IA tem função isolada, **sem autonomia para interagir diretamente com o banco** — preferida sobre padrões de tool/function-calling autônomo por risco de prompt injection. (Nuance importante: function calling continua sendo o mecanismo do fluxo de consulta, mas com o LLM apenas *preenchendo parâmetros* de operações pré-definidas, nunca com acesso livre ao banco.)
- **[design]** Modelos pequenos (SLMs) ou embeddings para a etapa de classificação, por custo — semente da estratégia que virou Nova Micro/Nova Lite.

## 8. Diagrama e stack — "Diagrama para bot financeiro Python" (23/07/2026)

- **[design]** Mapeamento do fluxo de consulta na arquitetura em camadas: handler recebe mensagem já classificada → service do agente orquestra o ciclo LLM ↔ ferramentas → cada ferramenta é um método do repositório com consulta de agregação (soma por categoria, total por período, maiores gastos). O LLM "estrutura a consulta" = preenche parâmetros (categoria, data inicial, data final).
- **[design]** Ponto-chave: **ferramentas retornam dados estruturados (resultado do SQL/query), nunca texto livre** — o passo final do LLM só narra números que já existem. Mesma garantia de confiabilidade da dedup: IA fora da parte determinística.
- Gerado diagrama SVG da arquitetura AWS baseado no CloudFormation, com marcação tracejada do que o desenho conceitual prevê mas o template ainda não cobre (ramo de conselho, retorno ao Telegram).

## 9. Esta conversa — CloudFormation revisado + plano de migração (25/07/2026)

- Template CloudFormation revisado e validado (cfn-lint + JSON da ASL): trust policy corrigida (`states.amazonaws.com`), permissões restritas por recurso, DynamoDB remodelado (PK `userId`, SK `timestamp#transactionId`, GSI por categoria), state machine completada com `Default`/`Fail` na Choice.
- **[decisão]** Migrar de google-genai (Gemini) para **AWS Bedrock** como motor de LLM/OCR.
- **[decisão]** Estratégia de custo: IA só em pontos estratégicos — **Nova Micro** para texto (extração/classificação) e **Nova Lite** para OCR (degrau multimodal mais barato), sem overkill. Descoberta que motivou a separação: DeepSeek V3.2 (do template original) é texto-puro, não serve para OCR.
- **[design]** O CloudFormation é **alinhamento arquitetural**, não deploy literal — o state machine original era mais diagrama do que orquestração.
- Confirmado no repo (github.com/vitovls/guardiao-financeiro): `main.py` com `run_polling()`, três handlers (text/photo/pdf), sem handler de consulta, ainda 100% Gemini + pasta local `fotos/` + SQLite.
- **[design]** Peça faltante identificada: o "escutador" — alvo é Telegram → webhook → API Gateway → Lambda receptora fina (valida secret token, dedup de `update_id`, `StartExecution`), substituindo o polling.
- **[decisão]** Plano de migração em fases (documento separado): Fase 0 fundação AWS → 1 Bedrock → 2 S3 → 3 DynamoDB → 4 webhook+Lambda → 5 Step Functions → 6 consultas. Dependência dura: decompor em Lambdas exige dados e arquivos já fora do disco local.

---

## Invariantes do projeto (síntese transversal)

O que atravessa todas as conversas e não pode ser violado em nenhuma fase:

1. Dedup determinística de 3 estados, sem IA na comparação.
2. Validação (Pydantic) da saída do LLM antes de qualquer dado virar registro financeiro.
3. Camadas handler → service → repository; lógica de negócio nunca em handler; IA nunca com acesso direto ao banco (arquitetura rígida).
4. Ferramentas de consulta retornam dados estruturados; o LLM narra, não calcula.
5. Function calling + agregação, não RAG.
6. Complexidade só quando necessária (sem RabbitMQ, sem LangChain, sem abstrações sem segunda implementação real).
7. Regras do agente em arquivo editável pelo usuário (estilo CLAUDE.md).
8. `Transacao` (DTO) separado de entidade de persistência.

## Links das conversas

- Bot Telegram com Python básico: https://claude.ai/chat/b1f9991c-7426-4f5d-9cd7-bc23301c6f26
- Arquitetura de bot Telegram com Gemini: https://claude.ai/chat/9f494564-e1b0-424a-a61e-662a506f1ecb
- Preparação para entrevista full stack: https://claude.ai/chat/dc627330-116a-47b8-ae95-a595fa8bc4da
- Frontend app para treinar LangChain: https://claude.ai/chat/454cf246-a72f-463a-a95f-1d8114e0a341e (menção lateral)
- EC2 para bot Python é overkill?: https://claude.ai/chat/450d3a82-1007-4091-85f5-22006dc63357
- Bot Telegram para gestão financeira com Gemini: https://claude.ai/chat/0a2ab1d5-15f6-4332-9e51-5f185cd70925
- Migração do Guardião Financeiro para AWS: https://claude.ai/chat/49eca077-9921-4b8e-8144-e4a6f548df28
- Diagrama para bot financeiro Python: https://claude.ai/chat/26b2faba-e85c-4fd9-9a55-24c6fb70fa9c