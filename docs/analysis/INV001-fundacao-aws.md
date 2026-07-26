---
type: INV
version: 1.0.0
author: Victor Veloso
date: 2026-07-26
status: Draft
---

# INV001 — Fundação AWS (Fase 0 do plano de migração)

## Contexto

**Gatilho:** `docs/analysis/plano-contexto.md`, seção "Fase 0 — Fundação AWS", é o plano de migração aprovado do monólito EC2 (Gemini + SQLite + polling) para a arquitetura serverless AWS (Bedrock + S3 + DynamoDB + Step Functions). A migração acontece em 7 fases (0 a 6), cada uma mantendo o bot funcional ao final. Este INV mapeia **apenas a Fase 0**, que é pré-requisito de todas as demais (nenhuma fase AWS seguinte pode começar sem credenciais e model access prontos).

**Branch:** `feat/bedrock-amazon`.

**Natureza da task:** infraestrutura/configuração de conta, não há lógica de negócio envolvida. Nenhum arquivo de `handlers/`, `services/` ou `repository/` é tocado nesta fase. O template `docs/guardiao-financeiro-stack.yml` é **referência arquitetural do alvo final**, não algo a ser deployado agora — confirmado explicitamente pelo usuário nesta sessão. `cloudformation deploy`/SAM só entram na Fase 5.

**Escopo desta fase, conforme o plano (seção "Fase 0" e lista de tarefas):**
- Definir e fixar região AWS.
- Criar IAM de desenvolvimento com política mínima (`bedrock:InvokeModel` nos dois ARNs de modelo).
- Habilitar model access de Nova Micro e Nova Lite no console Bedrock.
- Configurar credenciais (nesta fase, localmente; instance profile na EC2 fica para quando o smoke test for validado lá).
- Script de smoke test invocando os dois modelos.

**Critério de saída do plano:** "os dois modelos respondem a partir da EC2." Nesta rodada, o critério imediato é os dois modelos responderem **localmente** — a validação na EC2 fica registrada como próximo incremento natural, não como parte do escopo de saída desta fase (ver Decisões abaixo).

---

## Estado atual do entorno (o que já existe)

### Credenciais e configuração

- `run_polling/config.py:1-8` — único ponto de configuração hoje. Carrega `.env` via `python-dotenv` e expõe `BOT_TOKEN` e `GEMINI_API_KEY`. Nenhuma variável AWS existe ainda.
- `.env` contém só `BOT_TOKEN` e `GEMINI_API_KEY`. `.env.example` está vazio.
- AWS CLI **já instalado e configurado** nesta máquina (`/usr/local/bin/aws`), confirmado via `aws sts get-caller-identity`:
  - Conta: `413948096391`
  - Usuário IAM atual: `arn:aws:iam::413948096391:user/vitoveloso` (identidade pessoal — **não** deve ser reaproveitada como credencial do bot; é só o que criará o IAM de desenvolvimento).
  - Região default do CLI: `us-east-2` (`aws configure get region`).

### Dependências Python

- `requirements.txt` não lista `boto3`. `pip show boto3` confirma que não está instalado no `venv`.
- Versão atual mais recente do `boto3` no índice PyPI: `1.43.56`.
- Convenção do projeto (`requirements.txt` atual): todas as deps são pinadas com `==` (ex.: `google-genai==2.10.0`).

### Template CloudFormation (referência, não deploy)

`docs/guardiao-financeiro-stack.yml`:
- Linha 13: `BedrockTextModelArn` default = `arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-micro-v1:0` (Nova Micro, texto).
- Linha 21: `BedrockOcrModelArn` default = `arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-lite-v1:0` (Nova Lite, OCR/imagem).
- Linha 120-123: a policy de execução da Step Function no template já modela o padrão de permissão mínima que a Fase 0 deve replicar para o IAM de desenvolvimento: `Action: bedrock:InvokeModel` restrito aos dois ARNs acima (`!Ref BedrockTextModelArn` / `!Ref BedrockOcrModelArn`), não `bedrock:*`.
- Região `us-east-2` nos ARNs default bate com a região já configurada no CLI local — **não há conflito a resolver**.

### Estrutura de pastas

- Não existe pasta `scripts/` no repo hoje (só `handlers/`, `services/`, `repository/`, `database/`, `run_polling/`).
- `.gitignore` já ignora `.env`, `__pycache__/`, `venv/` — nenhum ajuste necessário para o smoke test (não vai gerar artefato novo a ignorar, além de possivelmente uma imagem de teste local, que deve ficar fora do repo ou em pasta já ignorada).

---

## Decisões de Produto Confirmadas (vieram do plano ou desta sessão — não são hipótese)

1. **Região fixada: `us-east-2`.** Confirmado pelo usuário e consistente com o default dos ARNs do template e com a região já configurada no AWS CLI local. Nenhuma decisão pendente aqui.
2. **Conta AWS e CLI já prontos** (`413948096391`, user `vitoveloso`). A Fase 0 não inclui bootstrap de CLI — só a criação do IAM de desenvolvimento dedicado.
3. **Model access do Bedrock (Nova Micro + Nova Lite) ainda não habilitado.** É passo manual no console AWS (Bedrock não expõe habilitação de model access via API/CLI de forma direta para contas novas) — documentado no TASKS como ação do usuário, fora do que o Claude Code pode executar.
4. **Smoke test roda primeiro localmente**, com as credenciais do IAM de desenvolvimento (não via instance profile — isso é validação de EC2, adiada). Local = mais rápido para iterar.
5. **Criação de recursos IAM (user, policy, attach) não é executada pelo Claude Code.** O TASKS deve produzir os comandos `aws iam ...` exatos e o JSON da policy para o usuário rodar manualmente e colar o output relevante (ex. Access Key) de volta. Espelha a mesma cautela já aplicada a ações git neste projeto: o usuário é o motor de decisão para qualquer ação com efeito real fora do repo.
6. **IAM mínimo por fase, incremental:** só `bedrock:InvokeModel` nos dois ARNs agora; `s3:*` some na Fase 2, `dynamodb:*` na Fase 3 (política de "ampliar, nunca conceder tudo de uma vez"). Esta é uma decisão que **fases futuras herdam** — candidata a `PATTERNS.md`.
7. **Credencial do bot na EC2 via instance profile/role**, nunca access key em `.env` — já decidido no plano (seção Fase 0, item "Configurar credenciais na EC2"). Nesta fase (smoke test local), usa-se uma access key do IAM de desenvolvimento **local**, mas o `.env`/instance profile de produção fica para quando a Fase 1 (`BedrockProvider`) rodar na EC2 de fato. Aqui documentamos só o método local de smoke test.
8. **Nome do IAM de desenvolvimento:** `guardiao-financeiro-dev` (user) + `guardiao-financeiro-dev-bedrock` (policy), seguindo a convenção de nomes já usada no template (`guardiao-financeiro-${Environment}-*`). Decisão de design de baixo risco, sem trade-off — não requer confirmação adicional do usuário.
9. **`boto3` pinado em `1.43.56`** (versão estável mais recente no momento), seguindo a convenção de pin exato do `requirements.txt`.
10. **Script de smoke test em `scripts/smoke_test_bedrock.py`** (pasta nova, fora do fluxo `handlers/→services/→repository/` — não é código de produção do bot, não precisa seguir a mesma disciplina de camadas).

---

## Relação com as fases seguintes

- Fase 1 (`BedrockProvider`) depende diretamente do resultado desta fase: model access habilitado + `boto3` funcional + confirmação de que Nova Micro/Lite respondem.
- A decisão de região (`us-east-2`) e o padrão de IAM incremental por fase valem para **todas** as fases seguintes (S3 na Fase 2, DynamoDB na Fase 3) — por isso vão para `PATTERNS.md` (ver `<decisoes_reutilizaveis>`), não só para este TASKS.
- Este INV não toca `CLAUDE.md`/`PATTERNS.md` diretamente — o TASKS que sair daqui é quem fará o broadcast da decisão de região/IAM incremental.

---

## Perguntas em Aberto

Nenhuma. Todas as lacunas identificadas durante a investigação foram resolvidas nesta sessão (ver "Decisões de Produto Confirmadas" acima).

---

## Próximos Passos — Classificação de Rota

**Rota: Design Conhecido (curta) → INV → TASKS.**

Justificativa: após a investigação, não sobra trade-off em aberto. O plano já prescreve a abordagem (IAM mínimo incremental, instance profile só em produção, credenciais fora do `.env`), a região já está confirmada e bate com o CLI local, e as únicas decisões de nomenclatura (nome do IAM, path do script, versão do boto3) são de baixo risco e não têm alternativa concorrente real. A decisão reutilizável (região + padrão de IAM incremental) será registrada em `PATTERNS.md` a partir do TASKS, sem precisar de SPEC/PLN — não há requisito de produto a especificar nem estratégia técnica com alternativas a comparar, é um checklist de setup de conta.

Aguardando confirmação do usuário para prosseguir direto para `TASKS003`.
