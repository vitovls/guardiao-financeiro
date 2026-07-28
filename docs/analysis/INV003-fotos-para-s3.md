---
type: INV
version: 1.0.0
author: Victor Veloso
date: 2026-07-26
status: Draft
fase: "Fase 2 — docs/analysis/plano-contexto.md"
---

# INV003 — Migração de arquivos temporários: `fotos/` local → S3

## Contexto

Gatilho: usuário pediu para iniciar a Fase 2 do plano de migração serverless (`docs/analysis/plano-contexto.md`, seção "Fase 2 — Arquivos: `fotos/` local → S3`). Branch atual: `main` (task ainda não tem branch própria — deve virar `feat/fotos-para-s3` antes de qualquer código, por convenção do `CLAUDE.md`).

Achado colateral: existe um worktree paralelo (`.worktrees/feature/nlp-query-totals`) com `query_service.py`/`intent_service.py` — trabalho de Fase 6 em andamento em outra branch. Não relacionado a esta task, não tocar.

Antes de investigar o código, uma rodada de perguntas ao usuário resolveu as ambiguidades que o `plano-contexto.md` deixava em aberto (ver "Decisões de Produto Confirmadas" abaixo).

## Problema 1 — Arquivos tocam disco local da EC2

### Descrição observada

Foto e PDF recebidos do Telegram são baixados para uma pasta local `fotos/` antes de qualquer processamento, e removidos só depois da extração via `try/finally`. Isso trava a decomposição em Lambda (Fase 4), que não tem disco persistente compartilhado, e é a limitação que a Fase 2 existe para resolver.

### Análise de causa raiz

`main.py` cria a pasta na inicialização (`os.makedirs("fotos", exist_ok=True)`) e os dois handlers escrevem/leem nela via `python-telegram-bot`'s `File.download_to_drive(path)`.

### Arquivos relevantes (estado atual, literal)

**`handlers/photo_handler.py`** (24 linhas, arquivo inteiro):
```python
import os

from services.message_service import format_message
from services.ocr_service import extract_photo_data
from services.transaction_service import save_transactions


async def get_photo(update, context):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"fotos/{photo.file_unique_id}.jpg"
    await update.message.reply_text("...")
    await file.download_to_drive(path)

    try:
        transactions = await extract_photo_data(path)
    finally:
        os.remove(path)

    await save_transactions(transactions, user_id)
    message = format_message(transactions)
    await update.message.reply_text(message, parse_mode="HTML")
```

**`handlers/pdf_handler.py`** (26 linhas, arquivo inteiro):
```python
import os

from telegram import Update

from services.message_service import format_message, split_message
from services.ocr_service import extract_photo_data
from services.transaction_service import save_transactions


async def get_pdf(update: Update, context):
    user_id = update.effective_user.id
    pdf = update.message.document
    pdf_file = await pdf.get_file()
    pdf_path = f"fotos/{pdf.file_unique_id}.pdf"
    await update.message.reply_text("...")
    await pdf_file.download_to_drive(pdf_path)

    try:
        transactions = await extract_photo_data(pdf_path)
    finally:
        os.remove(pdf_path)

    await save_transactions(transactions, user_id)
    msg = format_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
```

**`services/ocr_service.py`** (24 linhas, arquivo inteiro):
```python
import sys

from models import Transacao
from services.llm.factory import get_llm_provider

_provider = get_llm_provider()


async def extract_photo_data(image_path: str) -> list[Transacao]:
    with open(image_path, "rb") as f:
        file_bytes = f.read()

    if image_path.endswith(".jpg"):
        mime_type = "image/jpeg"
    elif image_path.endswith(".pdf"):
        mime_type = "application/pdf"
    else:
        raise ValueError(f"Formato não suportado: {image_path}")

    try:
        return await _provider.extract_document_transactions(file_bytes, mime_type)
    except Exception as exc:
        print(f"[ocr_service] falha ao extrair transação de documento: {exc}", file=sys.stderr)
        return []
```
`ocr_service.extract_photo_data` só usa o `image_path` para (a) ler bytes do disco e (b) inferir o mime-type pela extensão — o `LLMProvider.extract_document_transactions(file_bytes, mime_type)` já recebe bytes puros. Ou seja, o acoplamento a disco aqui é incidental, não estrutural.

**`main.py`** (linha 15): `os.makedirs("fotos", exist_ok=True)` roda incondicionalmente na inicialização.

### Evidência técnica (python-telegram-bot 22.8, verificado no venv do projeto)

- `telegram.File` tem `download_as_bytearray(self, buf=None, ...) -> bytearray` (`async`) — baixa o arquivo **direto para memória**, sem tocar disco. Hoje só `download_to_drive` é usado.
- `telegram.Document` já expõe `.mime_type` (string, vem do próprio Telegram) e `.file_size` (int). Hoje o mime-type é inferido pela extensão do path em `ocr_service.py` em vez de usar o campo que o Telegram já fornece.
- `telegram.PhotoSize` (o tipo de `update.message.photo[-1]`) também expõe `.file_size`.
- Isso significa que dá para checar o tamanho do arquivo **antes de baixar** (via `.file_size`, sem chamar `get_file()`/download) e determinar o mime-type sem olhar para nenhum path.

### Limite de tamanho de arquivo (verificado, não é suposição)

A Bot API do Telegram só permite baixar arquivos de até **20 MB** via `getFile` (limite documentado em `core.telegram.org/bots/faq`; arquivos maiores exigem um Bot API server local, fora de escopo). Esse é o teto natural para a checagem "arquivo grande demais → recusar" pedida no `plano-contexto.md`.

## Problema 2 — Sem bucket S3 e sem IAM para ele

### Descrição observada

Não existe hoje nenhum bucket S3 para o projeto, nem permissão IAM para `s3:*` na policy de desenvolvimento.

### Arquivos relevantes

**`scripts/aws/iam-policy-guardiao-dev.json`** (política atual, só Bedrock):
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
Por `PATTERNS.md` ("IAM mínimo incremental por fase"), esta é exatamente a policy que a Fase 2 deve ampliar com um novo `Sid` de S3 — nunca substituir, nunca abrir `s3:*`.

Conta AWS: `413948096391`, profile local `guardiao-dev`, região `us-east-2` (decisões já fixadas em `INV001`/`TASKS003`, reaproveitadas aqui).

### Estado do template CloudFormation (referência arquitetural, não deploy literal)

`docs/guardiao-financeiro-stack.yml` já modela o bucket-alvo, mas com nome genérico `MyDataBucket` / `guardiao-financeiro-dados-${Environment}-${AWS::AccountId}`, **sem lifecycle rule**, e usado em 4 lugares — todos precisam mudar juntos se o nome lógico mudar:

```yaml
# linha 5-9 (parâmetro usado no nome)
Parameters:
  Environment:
    Type: String
    Default: dev
    AllowedValues: [dev, homolog, prod]

# linha 32-43
  MyDataBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub 'guardiao-financeiro-dados-${Environment}-${AWS::AccountId}'
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256
```
```yaml
# linha 117 (IAM da role dos Steps Functions)
                Resource: !Sub '${MyDataBucket.Arn}/*'
```
```yaml
# linha 366 (parâmetro passado pro state "PutObject S3" do desenho, dentro do JSON do state machine)
          BucketNome: !Ref MyDataBucket
```
```yaml
# linha 372 (Outputs)
Outputs:
  BucketName:
    Value: !Ref MyDataBucket
```
Nenhuma `LifecycleConfiguration` existe hoje — precisa ser adicionada (Fase 2 pede expiração de 1 dia como rede de segurança do delete).

Como o template **não é deployado nesta fase** (só vira deploy real na Fase 5, por princípio do plano), atualizá-lo é documentação de alinhamento arquitetural, não infraestrutura viva — baixo risco, mas deve ser mantido em sincronia com o nome real do bucket criado manualmente.

## Relação entre os problemas

Os dois problemas são a mesma mudança vista de dois ângulos: Problema 1 é o código da aplicação que hoje depende do disco local; Problema 2 é a infraestrutura AWS que ainda não existe para substituí-lo. Nenhum dos dois é resolvível isoladamente — o código novo não tem para onde apontar sem o bucket, e o bucket sem o código novo não é usado.

## Decisões de Produto Confirmadas (usuário, nesta sessão)

1. **Flag de rollback `STORAGE_BACKEND=local|s3`.** A lista de tarefas do `plano-contexto.md` manda remover `fotos/`/`makedirs` já nesta fase, mas o Princípio 3 do plano ("toda troca de provedor fica atrás de flag até a fase seguinte confirmar estabilidade") pede o contrário. Resolvido: segue o Princípio 3, mesmo padrão do `LLM_PROVIDER` (Fase 1) — duas implementações vivas, flag por env var, remoção do fallback local adiada para depois de confirmada a estabilidade em produção (mesmo ciclo de vida do `GeminiProvider`, que só foi removido depois). Isso também dissolve a contradição: o critério de saída "nenhum arquivo toca o disco" vale para o modo padrão de produção (`s3`), não para o modo de rollback (`local`), que é transitório.
2. **Abstração via interface (`StorageProvider` ABC).** `PATTERNS.md` já registra que troca de dependência externa (LLM, banco, **storage**) segue o padrão interface+factory do `LLMProvider` (`services/llm/provider.py` + `factory.py`). Com a decisão (1) confirmada — duas implementações reais e vivas (`local`, `s3`) — a regra do `repository/` ("sem ABC sem 2ª implementação real") não bloqueia; pelo contrário, exige a interface. Resolvido: `services/storage/provider.py` (ABC) + `local_provider.py` + `s3_provider.py` + `factory.py`, espelhando a estrutura de `services/llm/`.
3. **Renomear "fotos" → "files" em três lugares**, já que a pasta/bucket guarda fotos e PDFs, não só fotos:
   - Pasta/prefixo local e chave S3 (código): `fotos/` vira `files/`.
   - Nome físico do bucket AWS: `guardiao-financeiro-dados-...` vira `guardiao-financeiro-files-dev-413948096391` (segue a convenção `guardiao-financeiro-{finalidade}-{Environment}-{AccountId}` já usada no template).
   - Nome lógico no CloudFormation: `MyDataBucket` vira `MyFilesBucket` (nos 4 pontos listados acima).
4. **Bucket ainda não existe.** O TASKS deve conter os comandos AWS CLI exatos (nome, `BlockPublicAcls`, `ServerSideEncryption` AES256, lifecycle de expiração em 1 dia) para o usuário rodar manualmente — por `PATTERNS.md` ("criação de recursos AWS é sempre ação manual do usuário"), o Claude Code nunca executa `aws s3 mb`/`aws s3api` diretamente.

## Observações de Runtime confirmadas pelo usuário

- Conta AWS `413948096391`, profile CLI `guardiao-dev`, região `us-east-2` — já configurados (Fase 0), reaproveitados sem mudança.
- `STORAGE_BACKEND` segue o padrão de nome de `LLM_PROVIDER`/`DB_BACKEND` já usado no projeto.

## Perguntas em Aberto

Nenhuma — todas as ambiguidades identificadas (flag vs. sem flag, abstração vs. concreto, nome do bucket) foram resolvidas nas rodadas de `AskUserQuestion` desta sessão (ver "Decisões de Produto Confirmadas").

## Próximos Passos

Causa raiz fechada, abordagem única e sem trade-off remanescente (todos resolvidos acima), nenhuma decisão desta task depende de exploração adicional. **Classificação: Design Conhecido.**

Rota proposta: **rota curta** — INV003 (este documento) → `TASKS005-fotos-para-s3.md`, com a "Decisão de Design" no próprio TASKS referenciando este INV, e broadcast para `docs/PATTERNS.md` (a decisão 1+2 acima é reutilizável pela Fase 3, que vai introduzir `DB_BACKEND=sqlite|dynamo` seguindo o mesmíssimo padrão).

⏸ Aguardando confirmação do usuário sobre a classificação antes de escrever o TASKS.
