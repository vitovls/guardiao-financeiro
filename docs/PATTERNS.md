# PATTERNS.md — Padrões e Decisões do Projeto

Leitura obrigatória em toda sessão de implementação.

## Padrões Estabelecidos

### DTO vs Entity — separação obrigatória

`models.Transacao` (Pydantic) é o contrato de extração do Gemini. `TransacaoEntity` (SQLAlchemy) é o que é persistido. Nunca fundir. O DTO não sabe que banco existe; a Entity não sabe que Gemini existe. A conversão ocorre no repository.

### Repository concreto sem interface

`repository/transacao.py` é uma classe concreta sem `Protocol`/`ABC`. Python tem duck typing: um teste pode passar um objeto fake com a mesma assinatura sem herança formal. Só revisar se aparecer uma segunda implementação real.

### Service como camada de orquestração intencional

`services/transaction_service.py` existe entre handler e repository por consistência arquitetural, não porque há lógica hoje. É o lugar reservado para dedup quando for implementado. Repasse direto é intencional, não cheiro de código.

### IA apenas na extração

`ocr_service.py` e `nlp_service.py` são os únicos pontos que chamam Gemini. Qualquer lógica de comparação, dedup ou decisão é determinística — sem chamada de IA, por determinismo, testabilidade e custo.

### Inserção em lote

`session.add()` para todas as entidades do lote, `session.commit()` uma vez só ao final. Nunca `commit()` dentro de loop.

### Arquivos temporários

Foto e PDF baixados para `fotos/` são removidos com `try/finally` imediatamente após o OCR, antes de qualquer outra operação.

## Decisões Estabelecidas

<!-- Preenchido pelo /map-task quando uma decisão for reutilizável por tasks futuras. -->

### Região AWS fixada: `us-east-2`

Toda a migração serverless (Bedrock, S3, DynamoDB, Step Functions) usa `us-east-2` — bate com os ARNs default do template `docs/guardiao-financeiro-stack.yml` e com o AWS CLI já configurado localmente. Nenhuma fase futura deve introduzir outra região sem revisar esta decisão. Origem: `docs/analysis/INV001-fundacao-aws.md` / `docs/tasks/TASKS003-fundacao-aws.md`.

### Nova Micro/Lite em `us-east-2` exigem inference profile, não o model ID puro

`us-east-2` não tem "In-Region" para `amazon.nova-micro-v1:0`/`amazon.nova-lite-v1:0` (só `us-east-1` tem) — chamar o model ID puro dá `ValidationException: ... on-demand throughput isn't supported`. É preciso usar o Geo cross-region inference profile ID (`us.amazon.nova-micro-v1:0` / `us.amazon.nova-lite-v1:0`), que roteia para `us-east-1`, `us-east-2`, `us-west-2`. A IAM policy precisa permitir `bedrock:InvokeModel` no ARN do inference-profile **e** no foundation-model das 3 regiões de destino — só o profile ARN não basta. Vale para qualquer código futuro que chame Bedrock a partir de `us-east-2` (Fase 1 — `BedrockProvider`). Origem: `docs/tasks/TASKS003-fundacao-aws.md`, confirmado em docs.aws.amazon.com/bedrock (model cards de Nova Micro/Lite).

### IAM mínimo incremental por fase

Cada fase da migração AWS amplia a mesma policy de desenvolvimento (`scripts/aws/iam-policy-guardiao-dev.json`) só com as permissões que aquela fase exige — nunca uma policy ampla de uma vez. Fase 0: `bedrock:InvokeModel` nos 2 ARNs de modelo. Fase 2 acrescenta S3; Fase 3 acrescenta DynamoDB. Origem: `docs/analysis/INV001-fundacao-aws.md` / `docs/tasks/TASKS003-fundacao-aws.md`.

### Criação de recursos AWS é sempre ação manual do usuário

Nenhuma task de migração deve fazer o Claude Code executar `aws iam`, `aws cloudformation deploy` ou similar diretamente. O TASKS produz os comandos exatos e o usuário roda, conferindo cada output — mesmo padrão de cautela já aplicado a ações git neste projeto. Origem: `docs/tasks/TASKS003-fundacao-aws.md`.

### Bootstrap de conta (criar bucket/tabela/etc.) roda com o profile admin, nunca com `guardiao-dev`

O usuário IAM `guardiao-financeiro-dev` (profile local `guardiao-dev`) só tem as permissões mínimas de runtime que o app precisa (ex.: `s3:PutObject`/`GetObject`/`DeleteObject`, nunca `s3:CreateBucket`/`s3:ListBucket`) — por design (`IAM mínimo incremental por fase`, acima). Ações de bootstrap de conta (criar bucket, criar tabela DynamoDB, criar a própria policy/usuário IAM) exigem permissão administrativa e devem rodar com o profile default do AWS CLI (identidade pessoal do usuário), nunca com `--profile guardiao-dev` — usá-lo aqui dá `AccessDenied`. Já era o padrão implícito em `TASKS003` T1 (`aws iam create-user`/`create-policy` sem `--profile guardiao-dev`); ficou explícito depois que o `TASKS005` T1 (criação do bucket S3) errou ao incluir `--profile guardiao-dev` nos comandos `aws s3api create-bucket`/etc., causando `AccessDenied` na execução real. Qualquer TASKS futuro com criação de recurso AWS (ex.: `aws dynamodb create-table` na Fase 3) deve omitir `--profile guardiao-dev` nesses comandos. Origem: `docs/tasks/TASKS005-fotos-para-s3.md`, descoberto na execução manual do T1.

### Troca de provedor externo: interface + factory por flag de ambiente

Toda troca de dependência externa (LLM, banco, storage) segue o mesmo padrão: uma interface ABC em `services/<dominio>/` com os contratos de domínio (nunca vazando o SDK do provedor), implementações concretas recebendo o client via injeção no construtor (`__init__(self, client=None)`, testável sem monkeypatch), e uma `factory.py` que lê uma flag de ambiente (`os.getenv("X_PROVIDER", "<default-atual>")`) e instancia a implementação certa — valor inválido levanta `ValueError` na inicialização, nunca cai silenciosamente num default errado. `ABC`/`Protocol` só se justifica aqui porque há ≥2 implementações reais desde o primeiro commit (diferente da regra de `repository/`, que exige uma segunda implementação real antes de introduzir abstração). Primeira aplicação: `LLMProvider` (`GeminiProvider`/`BedrockProvider`, flag `LLM_PROVIDER`). Fases futuras devem seguir o mesmo desenho: `DB_BACKEND=sqlite|dynamo` (Fase 3) reaproveita este padrão em vez de redecidir do zero. Origem: `docs/analysis/INV002-gemini-para-bedrock.md` / `docs/tasks/TASKS004-gemini-para-bedrock.md`.

### Bedrock Converse API exige `inferenceConfig.maxTokens` explícito

Sem esse parâmetro, o Converse API usa um default de **2000 tokens de saída** — insuficiente para extrair um extrato real com muitas transações (o JSON trunca no meio do array e falha a validação de output malformado, esgotando a re-tentativa de T7 e levantando `BedrockOutputError` sempre do mesmo jeito, já que é o mesmo documento truncando no mesmo ponto). Descoberto ao testar manualmente o cenário 4 de T9 (PDF real de extrato bancário) — não estava especificado em `TASKS004`. `BedrockProvider` agora passa `inferenceConfig={"maxTokens": 5000}` em toda chamada `converse()` (`_MAX_OUTPUT_TOKENS`); `5000` e `10000` foram confirmados aceitos pela API para Nova Micro/Lite em teste real. Qualquer código futuro que chame Bedrock Converse (Fase 2/3 ou outro provider) deve configurar `maxTokens` explicitamente — nunca confiar no default. Origem: `docs/tasks/TASKS004-gemini-para-bedrock.md`, descoberto em teste manual pós-implementação.

### Storage segue o mesmo padrão de troca de provedor externo (interface + factory + flag)

`StorageProvider` (`LocalStorageProvider`/`S3StorageProvider`, flag `STORAGE_BACKEND=local|s3`) reaplica o padrão já usado por `LLMProvider`/`LLM_PROVIDER`: interface ABC em `services/storage/`, implementações injetáveis via construtor (`client=None`, testável sem monkeypatch), factory que valida a flag e levanta `ValueError` em valor inválido. Confirma que a decisão "Troca de provedor externo" registrada acima vale, na prática, também para `storage`, não só para LLM — e reforça que `DB_BACKEND=sqlite|dynamo` (Fase 3) deve seguir o mesmo desenho em vez de redecidir do zero. Origem: `docs/analysis/INV003-fotos-para-s3.md` / `docs/tasks/TASKS005-fotos-para-s3.md`.

### `pytest.ini` precisa de `--import-mode=importlib` por causa de nomes de teste repetidos entre domínios

Sem `__init__.py` em `tests/` (padrão do projeto), o modo de import padrão do pytest (`prepend`) identifica cada módulo de teste só pelo basename — `tests/services/storage/test_provider.py` colide com `tests/services/llm/test_provider.py` (mesmo problema ocorre com `test_factory.py`), e o pytest aborta a coleta com `import file mismatch`. Resolvido adicionando `addopts = --import-mode=importlib` ao `pytest.ini`: resolve a colisão sem exigir `__init__.py` e sem renomear os arquivos (preserva o espelhamento `services/<domínio>/provider.py` → `tests/services/<domínio>/test_provider.py`). Qualquer fase futura que introduza um novo domínio seguindo o padrão interface+factory (ex.: `DB_BACKEND` na Fase 3, que também vai gerar `test_provider.py`/`test_factory.py` próprios) já está coberta por essa configuração — não precisa redescobrir o problema. Origem: `docs/tasks/TASKS005-fotos-para-s3.md`, descoberto ao rodar a suíte completa após introduzir `tests/services/storage/`.

### Test runner do projeto: pytest + pytest-asyncio

Primeira introdução de test runner (antes disso, nenhum configurado). `pytest==9.1.1` + `pytest-asyncio==1.4.0` (`pytest.ini` com `asyncio_mode = auto`, sem precisar marcar cada teste assíncrono manualmente). Testes ficam em `tests/`, espelhando a estrutura de `services/` (ex.: `services/llm/bedrock_provider.py` → `tests/services/llm/test_bedrock_provider.py`), sem `__init__.py` (mesmo padrão de namespace implícito já usado em `services/`/`handlers/`/`repository/`). Toda task nova que envolva lógica pura (parsing, validação, retry) deve ter teste automatizado seguindo TDD; chamadas reais a APIs externas (LLM, AWS) nunca entram em teste automatizado — só em cenários de teste manual. Origem: `docs/tasks/TASKS004-gemini-para-bedrock.md`.

### `TransactionRepository` ganha segunda implementação real (DynamoDB) — mesmo padrão de troca de provedor externo

`SqliteTransactionRepository`/`DynamoTransactionRepository` (flag `DB_BACKEND=sqlite|dynamo`) reaplicam o padrão interface+factory já usado por `LLMProvider`/`StorageProvider`. Diferença notável: a sessão SQLAlchemy deixou de ser injetada no construtor (quebrava o padrão "uma instância reutilizável do factory") — `SqliteTransactionRepository` agora abre sua própria sessão por operação via `session_factory` injetável. Origem: `docs/analysis/INV004-sqlite-para-dynamodb.md` / `docs/tasks/TASKS006-sqlite-para-dynamodb.md`.

### Dedup determinística: fingerprint no `sortKey`, nunca em atributo próprio

`sortKey = "{data ISO}#{sha256(valor+tipo+descrição normalizada)[:16]}"`. Qualquer código futuro que escreva transações (ex. um eventual importador, ou a Fase 6b) deve passar pelas funções puras de `repository/dedup.py` (`normalize_description`, `compute_fingerprint`, `is_similar`), nunca reimplementar a checagem. DUPLICATA_EXATA sempre bloqueia e nunca insere/descarta silenciosamente, mesmo em casos legítimos (ex. duas compras idênticas no mesmo dia) — decisão de produto deliberada, sem tratamento de adjacência/posição no lote. Origem: `docs/specs/SPEC006-sqlite-para-dynamodb.md` (B1-B3b) / `docs/tasks/TASKS006-sqlite-para-dynamodb.md`.

### `BatchWriteItem` do DynamoDB não suporta `ConditionExpression`

Qualquer escrita em lote no DynamoDB que precise de dedup (ou qualquer outra condição por item) usa `PutItem` individual condicional, nunca `boto3`'s `Table.batch_writer()` — a API `BatchWriteItem` não aceita condição por item. Vale para `DynamoTransactionRepository.save_transactions` e para `scripts/migrate_sqlite_to_dynamo.py`. Origem: `docs/plans/PLN006-sqlite-para-dynamodb.md`.

### `Query` por faixa de data num `sortKey` composto precisa de sentinela no limite superior

`sortKey` no formato `"{data}#{sufixo}"` não aceita um `BETWEEN`/`Key(...).between(...)` ingênuo com a data pura como limite superior — perde itens do último dia cujo sufixo ordena depois do que seria comparado. Usar um sentinela alto (`"{data_final}#￿"`) como limite superior. Vale para qualquer `Query` futura sobre essa tabela (busca de SUSPEITA, `get_totals_by_period`, e qualquer relatório futuro por período). Origem: `docs/plans/PLN006-sqlite-para-dynamodb.md`.

### Configuração (orçamento/dívida) é um único tipo de Item, sem ABC de repository

`ConfigItem`/`ConfigRepository` (`sortKey = "CONFIG#{nome}"`, campo `periodo` distingue balde recorrente de dívida sem-reset) — mesmo *shape*, confirmado por pesquisa de mercado (YNAB modela debt payoff na mesma estrutura de categoria/envelope, mudando só o *target type*). Saldo nunca é armazenado, sempre derivado de `get_totals_by_period`. `ConfigRepository` é uma classe concreta sem `ABC`/`Protocol` — só existe uma implementação real (Dynamo), mesma regra de `repository/` até hoje. A Fase 6b (agente de conselho) não deve redecidir esse formato do zero. Origem: `docs/analysis/INV004-sqlite-para-dynamodb.md`, `docs/specs/SPEC006-sqlite-para-dynamodb.md`.
