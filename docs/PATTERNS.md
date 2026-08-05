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

### Modelos Nova em `us-east-2` podem cercar a resposta em markdown — parser precisa ser tolerante

Diferentes tiers da família Nova formatam a resposta do Converse API de forma diferente: `nova-micro` responde JSON cru, `nova-lite` pode envolver a resposta em ` ```json ... ``` `. `BedrockProvider._call_with_malformed_retry` (`services/llm/bedrock_provider.py`) agora passa toda resposta por `_strip_markdown_fence` antes de `json.loads`, tolerando os dois formatos (com e sem cercamento, com ou sem a tag `json`). Qualquer troca futura de modelo Nova (ex.: fallback para `nova-pro` em `INV006`/`TASKS008`) deve assumir que o formato de cercamento pode mudar de novo — não assumir JSON cru por padrão. Origem: `docs/analysis/INV005-nova-micro-classificacao-texto.md` / `docs/tasks/TASKS007-nova-lite-classificacao-texto.md`.

### Fallback de modelo por robustez segue a mesma família Nova antes de trocar de provedor

Quando um modelo Nova (`nova-micro`/`nova-lite`) não é confiável o bastante para uma tarefa (classificação de texto, extração de documento), o primeiro fallback é o próximo tier da mesma família (`nova-pro`), não um provedor diferente — reaproveita o mesmo padrão de inference profile/IAM já estabelecido (`INV001`), só ampliando os `Statement`s existentes com o novo model ID, sem `Sid` novo. Trocar de provedor (ex. Claude via Bedrock) só se o próximo tier Nova também falhar — decisão registrada, não eliminada, mas não tentada nesta fase. Origem: `docs/analysis/INV006-nova-lite-extracao-documento-nao-deterministica.md` / `docs/tasks/TASKS008-nova-lite-extracao-documento.md`.

**Adendo (v1.2.0 do TASKS008):** essa regra cobre o eixo de **determinismo** — e `nova-pro` de fato resolveu esse eixo (contagem e descrição estáveis entre rodadas). A troca de provedor que aconteceu em seguida (`meta.llama4-maverick-17b-instruct-v1:0`) não foi por `nova-pro` ter falhado nesta regra, e sim por um eixo diferente e ortogonal — **precisão/segmentação de layout** (3 transações reais consistentemente ausentes em todas as rodadas, mesmo com contagem/descrição estáveis). Ou seja: "determinismo resolvido" e "precisão resolvida" são critérios independentes: um fallback pode passar no primeiro e falhar no segundo, e vice-versa. Qualquer fase futura que avalie um modelo para extração deve checar os dois eixos separadamente, não assumir que resolver um resolve o outro.

**Adendo (TASKS009):** `TEXT_MODEL_ID` também migrou de `nova-lite` para `meta.llama4-maverick-17b-instruct-v1:0`, generalizando a decisão para toda extração via LLM do projeto (texto e documento) — deixou de ser uma escolha isolada por fluxo. A decisão de pular o próximo tier Nova (`nova-pro`) antes de tentar foi deliberada: o modelo já estava validado no projeto para extração financeira semanticamente exigente, e o objetivo explícito era evitar reabrir um ciclo de ajuste de prompt já testado como caro em `TASKS008` (T3/T3b, duas iterações sem sucesso). Qualquer novo ponto de extração via LLM no projeto deve considerar `meta.llama4-maverick-17b-instruct-v1:0` como candidato padrão, não repetir a progressão nova-micro→nova-lite→nova-pro do zero. Origem: `docs/analysis/INV007-nova-lite-extracao-texto-tipo-valor-girias.md` / `docs/tasks/TASKS009-llama-maverick-extracao-texto.md`.

### `Transacao.categoria` nunca fica vazia — `DEFAULT_CATEGORIA = "outros"` garantido no DTO

`models.Transacao` tem um `field_validator` que converte `categoria` vazia (ou omitida) para `DEFAULT_CATEGORIA` ("outros"), incondicionalmente — vale para toda instância criada em qualquer parte do sistema (extração via LLM, leitura de `SqliteTransactionRepository`/`DynamoTransactionRepository`, migração). Por isso nenhum código downstream (repository, `message_service`) precisa (nem deve) validar/tratar `categoria == ""` de novo — é uma garantia estrutural do DTO, não um caso de borda a checar em cada consumidor. `services/message_service.py::format_message` avisa o usuário inline quando a categoria caiu no fallback ("categoria não identificada, salva como 'outros'"), sem fluxo de pergunta-e-espera-resposta (mesmo princípio "sem estado" de `SPEC006`). Editar a categoria depois de salva é feature separada, não implementada — ver `docs/analysis/CONTEXT003-editar-categoria-transacao.md`. Origem: discussão de produto durante `TASKS006-sqlite-para-dynamodb.md`.

### Gírias monetárias precisam de conversão explícita no prompt, nunca inferência livre do modelo

Gírias como "conto" não são universais no português do Brasil (podem significar R$1 ou, menos comumente, R$1000, a depender de região/época) — sem instrução explícita, o modelo aplicou uma conversão arbitrária (~×100, observada em `CONTEXT004`). Convenção adotada no projeto: 1 conto = R$1, documentada literalmente em `build_text_extraction_prompt` (`prompts.py`). Qualquer gíria monetária nova que o produto queira suportar precisa do mesmo tratamento — regra explícita no prompt, não confiança na interpretação do modelo. Origem: `docs/analysis/INV007-nova-lite-extracao-texto-tipo-valor-girias.md` / `docs/tasks/TASKS009-llama-maverick-extracao-texto.md`.

### `Transacao.valor` ausente/implícito segue o mesmo princípio de alerta inline de `categoria` vazia

Quando o texto do usuário claramente descreve uma transação mas não menciona um valor numérico explícito (ex.: "Gastei com mercado"), o prompt instrui o modelo a preencher `valor: 0.0` em vez de descartar a transação (`e_transacao: false`), e `services/message_service.py::format_message` avisa o usuário inline ("valor não identificado, revise") — mesmo padrão já usado para `categoria == DEFAULT_CATEGORIA`, sem fluxo de pergunta-e-espera-resposta (mesmo princípio "sem estado" de `SPEC006`). Qualquer novo campo que possa ficar ambíguo/ausente na extração via LLM deve seguir esse mesmo princípio: preencher um valor sentinela + alertar inline, não falhar silenciosamente nem bloquear o fluxo esperando confirmação. Origem: `docs/analysis/INV007-nova-lite-extracao-texto-tipo-valor-girias.md` / `docs/tasks/TASKS009-llama-maverick-extracao-texto.md`.

### Pendência de confirmação é um Item persistido (`PENDENTE#`), nunca em memória de processo

Quando uma transação candidata não pode ser classificada como `nova` com certeza determinística (colisão de fingerprint exato ou similaridade textual dentro da janela de dedup), o sistema grava uma pendência de confirmação como Item na mesma tabela (`sortKey = "PENDENTE#{uuid4().hex}"`, mesmo padrão de `ConfigItem`) em vez de decidir sozinho (bloquear ou salvar) ou guardar em `context.user_data`. A pendência nunca expira sozinha — só sai do estado "pendente" por confirmação explícita do usuário (botões inline). Esse padrão deve ser reaproveitado por qualquer feature futura que precise de "algo aguardando decisão do usuário, que sobrevive a restart" (ex.: uma eventual extensão do `CONTEXT003`, edição de transação). Origem: `docs/analysis/INV008-confirmacao-duplicata-exata.md` / `docs/specs/SPEC010-confirmacao-duplicata-exata.md` / `docs/tasks/TASKS010-confirmacao-duplicata-exata.md`.

### Timestamp de chegada (`criadoEm`) é atributo de Item/Entity, nunca do DTO `Transacao`

Quando uma feature precisa do momento real de chegada de uma mensagem (não a data de negócio, que é só `date`), o timestamp vive como atributo adicional no Item do DynamoDB (`criadoEm`, ISO datetime UTC), nunca em `models.Transacao` — mantém a separação DTO/Entity já estabelecida. Itens gravados antes dessa mudança não têm esse atributo; qualquer leitura que dependa dele precisa de um fallback explícito (usado aqui: meia-noite UTC da própria `data` de negócio). Origem: `docs/tasks/TASKS010-confirmacao-duplicata-exata.md`.

### Classificação de intenção (transação × consulta × nenhuma) vive na mesma chamada de IA que já extrai transação

Nunca uma segunda chamada de IA só para classificar intenção antes de decidir qual extração rodar — isso dobraria custo/latência de **toda** mensagem de texto, inclusive as que já são transação. Em vez disso, `LLMProvider.interpret_text` (substituiu `extract_text_transactions`) devolve um único DTO (`InterpretacaoTexto`, em `services/llm/provider.py`: `intencao: Literal["transacao", "consulta", "nenhuma"]`, `transacoes`, `periodo_inicio`/`periodo_fim`, `categoria`) numa única chamada ao provedor, com o prompt (`prompts.py::build_text_interpretation_prompt`) instruindo os três ramos no mesmo schema JSON. Qualquer nova intenção de texto que a Fase 6b ("conselhos financeiros") precise reconhecer deve estender esse mesmo DTO/prompt, não criar uma chamada de classificação separada. Origem: `docs/analysis/INV009-fluxo-consulta.md` / `docs/plans/PLN011-fluxo-consulta.md`.

### Filtro de categoria em consulta é feito em memória, com a mesma normalização da dedup — nunca via `GSI-Categoria`

A tabela real (`GuardiaoFinanceiro-Transacoes-dev`) tem `GSI-Categoria` ativo, mas nenhuma consulta o utiliza — filtro de categoria em `get_totals_by_period` (ambos os backends) compara `repository.dedup.normalize_description(categoria_pedida) == repository.dedup.normalize_description(categoria_salva)` sobre o resultado já trazido pela `Query` por período (chave primária), sem correspondência aproximada/sinônimos. Motivo: volume baixo de bot pessoal não justifica mais um caminho de leitura (mesmo raciocínio que arquivou as Fases 4/5 do `plano-contexto.md`); reaproveitar `normalize_description` (em vez de uma função nova) garante que a mesma transação seja encontrada da mesma forma nos dois backends (SQLite abandonou `GROUP BY` em favor de iteração em Python só para manter essa paridade). Qualquer ferramenta de consulta futura (Fase 6b, ex. "quanto posso gastar com lazer") que precise filtrar por categoria deve reaproveitar esse padrão, não redecidir do zero. Limitação conhecida e aceita: como a categoria é texto livre decidido pela IA no momento de salvar (sem enum/validação), uma consulta só encontra transações salvas com o **mesmo texto normalizado** — padronizar a criação de categoria é candidato a um INV próprio, não resolvido aqui. Origem: `docs/analysis/INV009-fluxo-consulta.md` / `docs/specs/SPEC011-fluxo-consulta.md` (R6) / `docs/plans/PLN011-fluxo-consulta.md`.

### Idempotência de entrega (`update_id`/`message_id`) usa TTL nativo do DynamoDB, não uma tabela/limpeza própria

Para descartar reentrega técnica de uma mensagem já processada (retry de webhook, restart no meio do processamento) sem reter esse controle para sempre, usa-se um Item (`sortKey = "PROCESSADO#{update_id}"`) com o atributo de TTL nativo da tabela (`expiraEm`, epoch seconds) — a tabela precisa ter TTL habilitado nesse atributo (`aws dynamodb update-time-to-live`, ação manual). Nunca confundir com a dedup de conteúdo (`DUPLICATA_EXATA`/`SUSPEITA`) — são eixos ortogonais. Origem: `docs/tasks/TASKS010-confirmacao-duplicata-exata.md`.
