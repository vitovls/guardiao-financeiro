---
type: TASKS
version: 1.0.0
author: Victor Veloso
date: 2026-07-26
status: Concluído
spec:
plan:
inv: INV001
---

# TASKS003 — Fundação AWS (Fase 0 do plano de migração)

## Contexto

Diagnóstico completo em `docs/analysis/INV001-fundacao-aws.md`. Resumo: nenhuma credencial/dependência AWS existe no repo hoje; AWS CLI já configurado localmente (conta `413948096391`, user `vitoveloso`, região `us-east-2`); `boto3` não instalado; sem pasta `scripts/`. O template `docs/guardiao-financeiro-stack.yml` é só referência arquitetural — nada aqui faz deploy dele.

Esta task **não toca `handlers/`, `services/`, `repository/` nem `models.py`**. É puramente fundação de conta AWS + um script avulso de smoke test. Nenhuma pergunta em aberto restou do INV.

## Decisão de Design

1. **Região fixada: `us-east-2`** — bate com os ARNs default do template e com a região já configurada no CLI local. Decisão herdada por todas as fases seguintes (S3, DynamoDB) → registrada em `PATTERNS.md`.
2. **IAM de desenvolvimento criado manualmente pelo usuário**, nunca pelo Claude Code. Esta task só produz o JSON da policy e os comandos exatos `aws iam ...` — o usuário roda e cola o resultado. Mesma cautela já aplicada a ações git neste projeto: efeito real fora do repo exige o usuário como motor de decisão.
3. **Nome dos recursos IAM:** user `guardiao-financeiro-dev`, policy `guardiao-financeiro-dev-bedrock`, seguindo a convenção `guardiao-financeiro-${Environment}-*` já usada no template.
4. **Credencial local via profile nomeado do AWS CLI (`guardiao-dev`)**, não via `.env` — `.env` fica reservado às variáveis de aplicação (`BOT_TOKEN`, `GEMINI_API_KEY`); credencial AWS de desenvolvimento vive em `~/.aws/credentials`, fora do repo. Instance profile na EC2 só entra quando a Fase 1 (`BedrockProvider`) rodar em produção — fora de escopo aqui.
5. **`boto3==1.43.56`** (versão estável mais recente), seguindo a convenção de pin exato do `requirements.txt`.
6. **Script de smoke test em `scripts/smoke_test_bedrock.py`**, fora    do fluxo `handlers/→services/→repository/` — não é código de produção do bot. Testa só conectividade/formato de request, não qualidade de OCR: a imagem usada é um PNG 1x1 sintético embutido no próprio script, para não introduzir dependência de imagem (Pillow) nem exigir um arquivo de teste externo.
7. **IAM mínimo incremental por fase:** só `bedrock:InvokeModel` nos dois ARNs de modelo agora. Amplia-se a mesma policy (`scripts/aws/iam-policy-guardiao-dev.json`) nas fases seguintes (S3 na Fase 2, DynamoDB na Fase 3) em vez de conceder tudo de uma vez.

---

## Progresso

- [x] T1 — Adicionar `boto3` a `requirements.txt`
- [x] T2 — Criar policy JSON + comandos `aws iam` (usuário executou; policy corrigida para inference profile após gap descoberto em T4)
- [x] T3 — ~~Habilitar model access no console Bedrock~~ (obsoleto: AWS removeu esse passo, ativação agora é automática no primeiro invoke)
- [x] T4 — Smoke test rodou com sucesso: `AWS_PROFILE=guardiao-dev python scripts/smoke_test_bedrock.py` → `[Nova Micro / texto] OK -> 'Brasília'` e `[Nova Lite / imagem] OK -> ...` (2026-07-26)

---

## Ordem de Execução

T1 → T2 → T3 → T4

(T2 e T3 podem ser feitas em paralelo entre si — ambas são pré-requisito só de T4.)

---

## T1 — Adicionar `boto3` a `requirements.txt`

**Arquivo:** `requirements.txt`

**Antes:**
```
google-genai==2.10.0
python-dotenv==1.2.2
python-telegram-bot==22.8
sqlalchemy==2.0.51
aiosqlite==0.22.1
```

**Depois:**
```
google-genai==2.10.0
python-dotenv==1.2.2
python-telegram-bot==22.8
sqlalchemy==2.0.51
aiosqlite==0.22.1
boto3==1.43.56
```

**Comando:** `source venv/bin/activate && pip install -r requirements.txt`

**Critério de aceitação:** `python -c "import boto3; print(boto3.__version__)"` imprime `1.43.56` sem erro.

---

## T2 — Criar policy JSON e comandos IAM (ação manual do usuário)

**Correção pós-implementação (2026-07-26):** a policy original (abaixo, primeira versão) previa acesso direto ao foundation-model em `us-east-2`. Na prática o smoke test (T4) falhou com `ValidationException: ... on-demand throughput isn't supported`, porque **`us-east-2` não tem "In-Region" para Nova Micro/Lite** — só existe via *Geo cross-region inference profile* (`us.amazon.nova-micro-v1:0` / `us.amazon.nova-lite-v1:0`, roteando para `us-east-1`, `us-east-2`, `us-west-2`). A policy final abaixo já reflete essa correção: acesso ao inference-profile (região de origem) **e** ao foundation-model nas 3 regiões de destino, para os dois modelos. Fonte: páginas oficiais de cada modelo em docs.aws.amazon.com/bedrock (regional availability + geo inference details).

**Arquivo:** `scripts/aws/iam-policy-guardiao-dev.json`

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "BedrockInvokeGeoInferenceProfileGuardiaoDev",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:us-east-2:413948096391:inference-profile/us.amazon.nova-micro-v1:0",
        "arn:aws:bedrock:us-east-2:413948096391:inference-profile/us.amazon.nova-lite-v1:0"
      ]
    },
    {
      "Sid": "BedrockInvokeFoundationModelGuardiaoDev",
      "Effect": "Allow",
      "Action": "bedrock:InvokeModel",
      "Resource": [
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-micro-v1:0",
        "arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-micro-v1:0",
        "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-micro-v1:0",
        "arn:aws:bedrock:us-east-1::foundation-model/amazon.nova-lite-v1:0",
        "arn:aws:bedrock:us-east-2::foundation-model/amazon.nova-lite-v1:0",
        "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-lite-v1:0"
      ]
    }
  ]
}
```

**Comando adicional para atualizar a policy já criada** (o usuário já rodou o `create-policy` original — IAM não permite editar in-place, precisa de uma nova versão):
```bash
aws iam create-policy-version \
  --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock \
  --policy-document file://scripts/aws/iam-policy-guardiao-dev.json \
  --set-as-default
```

**Comandos — o usuário roda manualmente, um de cada vez, conferindo o output antes de seguir para o próximo (Claude Code não executa estes comandos):**

```bash
# 1. Criar o usuário IAM dedicado (não usar a identidade pessoal vitoveloso)
aws iam create-user --user-name guardiao-financeiro-dev

# 2. Criar a policy mínima a partir do arquivo do repo
aws iam create-policy \
  --policy-name guardiao-financeiro-dev-bedrock \
  --policy-document file://scripts/aws/iam-policy-guardiao-dev.json

# 3. Anexar a policy ao usuário (substituir ACCOUNT_ID se diferente de 413948096391)
aws iam attach-user-policy \
  --user-name guardiao-financeiro-dev \
  --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock

# 4. Gerar a access key (o SecretAccessKey só aparece nesta resposta, uma vez)
aws iam create-access-key --user-name guardiao-financeiro-dev

# 5. Configurar um profile local dedicado com o AccessKeyId/SecretAccessKey do passo 4
aws configure --profile guardiao-dev
#   AWS Access Key ID: <do passo 4>
#   AWS Secret Access Key: <do passo 4>
#   Default region name: us-east-2
#   Default output format: json
```

**Critério de aceitação:** `aws sts get-caller-identity --profile guardiao-dev` retorna `arn:aws:iam::413948096391:user/guardiao-financeiro-dev` (não o `vitoveloso`).

---

## T3 — Habilitar model access no console Bedrock (ação manual do usuário)

**Obsoleto — a AWS aposentou a página "Model access".** Modelos serverless (incluindo Nova Micro/Lite) agora são habilitados automaticamente na conta no primeiro `InvokeModel`/`Converse`, sem passo manual de ativação. Confirmado pelo próprio console em 2026-07-26.

**Critério de aceitação (revisado):** a primeira chamada bem-sucedida do T4 já é a prova de que o acesso foi concedido — não há mais um passo prévio distinto de "Access granted" a verificar.

---

## T4 — Criar script de smoke test

**Arquivo novo:** `scripts/smoke_test_bedrock.py`

```python
import base64
import os
import sys

import boto3

REGION = os.getenv("AWS_REGION", "us-east-2")
TEXT_MODEL_ID = "amazon.nova-micro-v1:0"
IMAGE_MODEL_ID = "amazon.nova-lite-v1:0"

# PNG 1x1 vermelho, só para validar o caminho multimodal — não é teste de OCR.
_TEST_IMAGE_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
    "+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def test_text_model(client) -> None:
    response = client.converse(
        modelId=TEXT_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [{"text": "Responda em uma palavra: qual a capital do Brasil?"}],
            }
        ],
    )
    text = response["output"]["message"]["content"][0]["text"]
    print(f"[Nova Micro / texto] OK -> {text!r}")


def test_image_model(client) -> None:
    image_bytes = base64.b64decode(_TEST_IMAGE_B64)
    response = client.converse(
        modelId=IMAGE_MODEL_ID,
        messages=[
            {
                "role": "user",
                "content": [
                    {"image": {"format": "png", "source": {"bytes": image_bytes}}},
                    {"text": "Descreva o que você vê nesta imagem em uma frase curta."},
                ],
            }
        ],
    )
    text = response["output"]["message"]["content"][0]["text"]
    print(f"[Nova Lite / imagem] OK -> {text!r}")


def main() -> int:
    client = boto3.client("bedrock-runtime", region_name=REGION)
    try:
        test_text_model(client)
        test_image_model(client)
    except Exception as exc:
        print(f"FALHOU: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

**Comando:** `AWS_PROFILE=guardiao-dev python scripts/smoke_test_bedrock.py` (venv ativado, a partir da raiz do repo — atenção: o profile local é `guardiao-dev`, não o nome do IAM user `guardiao-financeiro-dev`).

**Nota:** `TEXT_MODEL_ID`/`IMAGE_MODEL_ID` usam os Geo inference profile IDs (`us.amazon.nova-micro-v1:0` / `us.amazon.nova-lite-v1:0`), não o model ID puro — ver correção em T2.

**Critério de aceitação:** imprime as duas linhas `[Nova Micro / texto] OK -> ...` e `[Nova Lite / imagem] OK -> ...` e sai com código `0`.

---

## Regra do Escoteiro — Testes

Nenhum test runner configurado (`CLAUDE.md`). Critério de conclusão desta task: smoke test do T4 rodando com sucesso, conforme os Cenários de Teste Manual abaixo.

---

## Cenários de Teste Manual

| Cenário | Resultado esperado |
|---|---|
| `aws sts get-caller-identity --profile guardiao-dev` após T2 | Retorna o ARN de `guardiao-financeiro-dev`, não de `vitoveloso` |
| Rodar T4 antes de T3 (model access ainda não habilitado) | Erro `AccessDeniedException` no stderr, saída de código 1 |
| Rodar T4 sem `AWS_PROFILE` ou com profile inexistente | Erro de credenciais (`NoCredentialsError`/`ProfileNotFound`) no stderr |
| Rodar T4 com T1, T2 e T3 completos | As duas linhas `OK` impressas, saída de código 0 |

---

## Fora de Escopo

- Instance profile/role da EC2 (fica para quando o `BedrockProvider` da Fase 1 rodar em produção).
- Qualquer alteração em `services/`, `handlers/`, `repository/`, `prompts.py` ou `models.py` — pertence à Fase 1.
- Ampliação da IAM policy para S3 (Fase 2) ou DynamoDB (Fase 3).
- Deploy do CloudFormation (`docs/guardiao-financeiro-stack.yml`) — só na Fase 5.
- Remoção do Gemini/`GEMINI_API_KEY` — só após estabilidade do Bedrock confirmada (pós Fase 1).
