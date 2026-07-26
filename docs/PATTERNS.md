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
