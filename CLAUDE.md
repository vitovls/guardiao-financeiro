# CLAUDE.md — Memória do Projeto

## Rodar a aplicação

```bash
source venv/bin/activate
python main.py
```

## Stack e Versões

| Componente | Versão |
|---|---|
| Python | 3.12.3 |
| python-telegram-bot | 22.8 |
| google-genai (Gemini SDK) | 2.10.0 |
| SQLAlchemy (async) | 2.0.51 |
| aiosqlite | 0.22.1 |
| python-dotenv | 1.2.2 |
| boto3 (AWS/Bedrock SDK) | 1.43.56 |
| pytest | 9.1.1 |
| pytest-asyncio | 1.4.0 |

**Banco de dados:** SQLite local (`guardiao.db`), sem Alembic — migrações são feitas via `init_db()` (create_all).

**Gemini model:** `gemini-2.5-flash` é o padrão atual. A seleção de modelo por caso de uso está em aberto — [a confirmar] conforme o projeto evoluir.

## Arquitetura

Entrypoint: `main.py` — inicializa o banco, monta o `Application` do python-telegram-bot e registra os handlers.

**Fluxo de dados:**

- Texto → `handlers/text_handler.py` → `services/nlp_service.py` (Gemini classifica e extrai) → `services/message_service.py`
- Foto → `handlers/photo_handler.py` → `services/ocr_service.py` (Gemini OCR) → `services/message_service.py`
- PDF → `handlers/pdf_handler.py` → `services/ocr_service.py` → `services/message_service.py`

**Camadas:**

```
handlers/      → apresentação: orquestra, zero lógica de negócio
services/      → lógica de aplicação
repository/    → acesso a dados
database/      → infraestrutura (engine, Base, entities)
models.py      → DTO Pydantic (Transacao)
prompts.py     → constantes de prompt para o Gemini
run_polling/   → config (variáveis de ambiente)
```

**Modelo de domínio:**

- `models.py` — `Transacao` (Pydantic `BaseModel`): `data: date`, `description: str`, `value: float`, `type: "income"|"expense"`, `category: str`. Retorno padrão de todos os services.
- `prompts.py` — `TRANSACTION_SCHEMA`: schema JSON enviado ao Gemini. Toda chamada nova ao Gemini deve importar daqui.

## O que Sempre Fazer

- Identificadores em **inglês**: funções, variáveis, parâmetros, métodos e nomes de arquivo.
- Commits: `emoji + conventional commit + descrição em pt-BR` (ex: `✨ feat: adiciona suporte a múltiplas contas`).
- DTO (`Transacao`) e Entity (`TransacaoEntity`) sempre separados — nunca fundir.
- `list[Transacao]` como tipo de retorno padrão entre camadas.
- Arquivos temporários (fotos, PDFs) removidos com `try/finally` após uso.
- Inserções no banco em lote: `session.add()` para todos, `commit()` uma vez.
- Todo novo ponto de entrada que chame Gemini deve importar `TRANSACTION_SCHEMA` de `prompts.py`.

## O que Nunca Fazer

- Lógica de negócio em `handlers/` — só orquestração.
- Chamar Gemini fora de `ocr_service.py` ou `nlp_service.py`.
- Fundir `Transacao` (DTO) com `TransacaoEntity` (SQLAlchemy).
- `commit()` dentro de um loop de inserção.
- Adicionar `Protocol`/`ABC` ao repository sem uma segunda implementação real ou necessidade concreta de teste.

## Variáveis de Ambiente

| Variável | Descrição |
|---|---|
| `BOT_TOKEN` | Token do bot gerado pelo @BotFather |
| `GEMINI_API_KEY` | Chave da API do Google Gemini |

## Testes

`pytest` + `pytest-asyncio` (`pytest.ini` com `asyncio_mode = auto`). Rodar com `pytest` na raiz. Testes ficam em `tests/`, espelhando a estrutura de `services/` (ex.: `services/llm/bedrock_provider.py` → `tests/services/llm/test_bedrock_provider.py`), sem `__init__.py`. Chamadas reais a LLM/AWS nunca entram em teste automatizado — só client mockado; cenários end-to-end ficam como "Cenários de Teste Manual" no TASKS. Decisão registrada em `docs/PATTERNS.md` (origem: `TASKS004-gemini-para-bedrock.md`).

## Fluxo de Trabalho (SDD)

Toda tarefa passa por:
1. `/map-task [descrição]` — investiga, documenta e aprova o pacote em `docs/`.
2. `/clear`
3. `/start-task docs/tasks/TASKSXXX-slug.md` — implementa com TDD a partir do doc aprovado.

## Branches

- **Nunca implementar direto na `main`.** Cada INV (`docs/analysis/INVXXX-*.md`) e cada fase da lista de tarefas de `docs/analysis/plano-contexto.md` (seção "Lista de tarefas") vira sua própria branch antes de qualquer código.
- Convenção de nome: `feat/{slug}` (ex.: `feat/fundacao-aws` para a Fase 0, `feat/bedrock-provider` para a Fase 1).
- Ao concluir a fase/INV, abrir PR de `feat/{slug}` → `main` para revisão — sem merge direto local.

Leitura obrigatória antes de tocar código: este arquivo e `docs/PATTERNS.md`.

## AWS Guidance

- Prefer the AWS MCP Server for AWS interactions — it provides sandboxed
  execution, observability, and audit logging. If unavailable, use the
  AWS CLI directly.
- Before starting a task, check whether a relevant AWS skill is available.
  Load the skill with `retrieve_skill` and prefer its guidance over
  general knowledge.
- When uncertain about specific AWS details (API parameters, permissions,
  limits, error codes), verify against documentation rather than guessing.
  State uncertainty explicitly if you cannot confirm.
- When creating infrastructure, prefer infrastructure-as-code (AWS CDK or
  CloudFormation) over direct CLI commands.
- When working with infrastructure, follow AWS Well-Architected Framework
  principles.
- Do not use em dashes in AWS resource names or descriptions. Use
  hyphens instead.

### Secret Safety

- MUST load the `aws-secrets-manager` skill first for any secret,
  credential, API key, token, or password task. MUST NOT call
  `secretsmanager get-secret-value` or `batch-get-secret-value`, and MUST
  NOT hit the Secrets Manager Agent daemon directly. MUST use
  `{{resolve:secretsmanager:secret-id:SecretString:json-key}}` with
  `asm-exec` so the secret resolves at runtime without entering context.
