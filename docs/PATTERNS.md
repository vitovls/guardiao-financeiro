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

### Troca de provedor externo: interface + factory por flag de ambiente

Toda troca de dependência externa (LLM, banco, storage) segue o mesmo padrão: uma interface ABC em `services/<dominio>/` com os contratos de domínio (nunca vazando o SDK do provedor), implementações concretas recebendo o client via injeção no construtor (`__init__(self, client=None)`, testável sem monkeypatch), e uma `factory.py` que lê uma flag de ambiente (`os.getenv("X_PROVIDER", "<default-atual>")`) e instancia a implementação certa — valor inválido levanta `ValueError` na inicialização, nunca cai silenciosamente num default errado. `ABC`/`Protocol` só se justifica aqui porque há ≥2 implementações reais desde o primeiro commit (diferente da regra de `repository/`, que exige uma segunda implementação real antes de introduzir abstração). Primeira aplicação: `LLMProvider` (`GeminiProvider`/`BedrockProvider`, flag `LLM_PROVIDER`). Fases futuras devem seguir o mesmo desenho: `DB_BACKEND=sqlite|dynamo` (Fase 3) reaproveita este padrão em vez de redecidir do zero. Origem: `docs/analysis/INV002-gemini-para-bedrock.md` / `docs/tasks/TASKS004-gemini-para-bedrock.md`.

### Bedrock Converse API exige `inferenceConfig.maxTokens` explícito

Sem esse parâmetro, o Converse API usa um default de **2000 tokens de saída** — insuficiente para extrair um extrato real com muitas transações (o JSON trunca no meio do array e falha a validação de output malformado, esgotando a re-tentativa de T7 e levantando `BedrockOutputError` sempre do mesmo jeito, já que é o mesmo documento truncando no mesmo ponto). Descoberto ao testar manualmente o cenário 4 de T9 (PDF real de extrato bancário) — não estava especificado em `TASKS004`. `BedrockProvider` agora passa `inferenceConfig={"maxTokens": 5000}` em toda chamada `converse()` (`_MAX_OUTPUT_TOKENS`); `5000` e `10000` foram confirmados aceitos pela API para Nova Micro/Lite em teste real. Qualquer código futuro que chame Bedrock Converse (Fase 2/3 ou outro provider) deve configurar `maxTokens` explicitamente — nunca confiar no default. Origem: `docs/tasks/TASKS004-gemini-para-bedrock.md`, descoberto em teste manual pós-implementação.

### Test runner do projeto: pytest + pytest-asyncio

Primeira introdução de test runner (antes disso, nenhum configurado). `pytest==9.1.1` + `pytest-asyncio==1.4.0` (`pytest.ini` com `asyncio_mode = auto`, sem precisar marcar cada teste assíncrono manualmente). Testes ficam em `tests/`, espelhando a estrutura de `services/` (ex.: `services/llm/bedrock_provider.py` → `tests/services/llm/test_bedrock_provider.py`), sem `__init__.py` (mesmo padrão de namespace implícito já usado em `services/`/`handlers/`/`repository/`). Toda task nova que envolva lógica pura (parsing, validação, retry) deve ter teste automatizado seguindo TDD; chamadas reais a APIs externas (LLM, AWS) nunca entram em teste automatizado — só em cenários de teste manual. Origem: `docs/tasks/TASKS004-gemini-para-bedrock.md`.
