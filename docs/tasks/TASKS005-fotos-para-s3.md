---
type: TASKS
version: 1.0.0
author: Victor Veloso
date: 2026-07-26
status: Concluído
spec:
plan:
inv: INV003
fase: "Fase 2 — docs/analysis/plano-contexto.md"
branch: feat/fotos-para-s3
---

# TASKS005 — Migração de arquivos temporários: `fotos/` local → S3

Diagnóstico completo em `docs/analysis/INV003-fotos-para-s3.md`. Resumo: `photo_handler.py`/`pdf_handler.py` baixam pro disco local (`fotos/`) via `File.download_to_drive`; `ocr_service.py` só usa o path pra ler bytes + inferir mime-type por extensão (acoplamento incidental — o `LLMProvider` já recebe bytes puros); não existe bucket S3 nem permissão IAM. `python-telegram-bot` 22.8 já oferece `File.download_as_bytearray()` (memória, sem disco) e `Document`/`PhotoSize` já expõem `.mime_type`/`.file_size` nativos — dá pra eliminar o path por completo. Limite de 20MB confirmado na FAQ oficial do Telegram.

**Branch:** esta task roda em `feat/fotos-para-s3`, nunca direto na `main` (convenção do `CLAUDE.md`). Criar a branch antes do T3.

## Decisão de Design

Três decisões foram fechadas com o usuário durante o `/map-task` (detalhadas em INV003, seção "Decisões de Produto Confirmadas") e são vinculantes para esta implementação:

1. **Flag `STORAGE_BACKEND=local|s3`**, mesmo ciclo de vida do `LLM_PROVIDER` (Fase 1): duas implementações reais e vivas, default inicial `local` (comportamento atual, seguro), troca para `s3` depois de validado, remoção do fallback local adiada para depois de confirmada a estabilidade — **fora de escopo desta task**.
2. **Abstração via `StorageProvider` (ABC)** em `services/storage/`, espelhando a estrutura de `services/llm/` (`provider.py` + `<impl>_provider.py` + `factory.py`), conforme `PATTERNS.md` → "Troca de provedor externo: interface + factory por flag de ambiente".
3. **Rename "fotos" → "files"** em três camadas: pasta/prefixo local e chave S3 (código), nome físico do bucket AWS, nome lógico no CloudFormation (`MyDataBucket` → `MyFilesBucket`, 4 ocorrências).

Nome do bucket: `guardiao-financeiro-files-dev-413948096391` (segue a convenção `guardiao-financeiro-{finalidade}-{Environment}-{AccountId}` do template; conta/região já fixadas em `INV001`/`TASKS003`: `413948096391`, `us-east-2`, profile CLI `guardiao-dev`).

Limite de tamanho: **20 MB** (`MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024`), teto real da Bot API do Telegram para `getFile` — checar via `.file_size` do `PhotoSize`/`Document` **antes** de baixar, não só antes de subir pro storage.

## T1 — Criar o bucket S3 (ação manual do usuário)

Por `PATTERNS.md` ("criação de recursos AWS é sempre ação manual"), o Claude Code nunca roda estes comandos — só os documenta aqui para o usuário executar.

**Correção pós-implementação:** criação de bucket é ação de bootstrap de conta, não permissão de runtime do app — o usuário IAM `guardiao-financeiro-dev` (perfil `guardiao-dev`) só tem `PutObject`/`GetObject`/`DeleteObject` (mínimo necessário em produção), sem `s3:CreateBucket`. `aws s3api create-bucket` com `--profile guardiao-dev` falha com `AccessDenied`. Mesmo padrão já usado em `TASKS003` T1 (`aws iam create-user`/`create-policy` rodaram sem `--profile guardiao-dev`, só com a identidade admin padrão do CLI): os comandos abaixo rodam **sem** `--profile guardiao-dev`, usando o profile default (admin) do AWS CLI.

```bash
aws s3api create-bucket \
  --bucket guardiao-financeiro-files-dev-413948096391 \
  --region us-east-2 \
  --create-bucket-configuration LocationConstraint=us-east-2

aws s3api put-public-access-block \
  --bucket guardiao-financeiro-files-dev-413948096391 \
  --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true

aws s3api put-bucket-encryption \
  --bucket guardiao-financeiro-files-dev-413948096391 \
  --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'

aws s3api put-bucket-lifecycle-configuration \
  --bucket guardiao-financeiro-files-dev-413948096391 \
  --lifecycle-configuration '{"Rules":[{"ID":"ExpireObjectsAfterOneDay","Status":"Enabled","Filter":{"Prefix":""},"Expiration":{"Days":1}}]}'
```

**Critério de aceitação:** `aws s3api get-bucket-lifecycle-configuration --bucket guardiao-financeiro-files-dev-413948096391` (sem `--profile guardiao-dev`, mesmo motivo acima) retorna a regra `ExpireObjectsAfterOneDay` com `Days: 1`.

## T2 — Ampliar a IAM policy de desenvolvimento com S3

**Arquivo:** `scripts/aws/iam-policy-guardiao-dev.json` — Claude Code edita o arquivo (é código no repo); o usuário roda os comandos AWS CLI depois.

**Depois** (adicionar este `Statement` ao array existente, sem tocar nos dois já presentes):
```json
    {
      "Sid": "S3ReadWriteDeleteFilesGuardiaoDev",
      "Effect": "Allow",
      "Action": [
        "s3:PutObject",
        "s3:GetObject",
        "s3:DeleteObject"
      ],
      "Resource": "arn:aws:s3:::guardiao-financeiro-files-dev-413948096391/*"
    }
```

Comandos para o usuário rodar após o commit (mesma mecânica do `TASKS003`, nova *policy version*):
```bash
aws iam create-policy-version \
  --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock \
  --policy-document file://scripts/aws/iam-policy-guardiao-dev.json \
  --set-as-default \
  --profile guardiao-dev
```

**Critério de aceitação:** `aws iam get-policy-version --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock --version-id <nova-versao> --profile guardiao-dev` mostra o `Sid` `S3ReadWriteDeleteFilesGuardiaoDev`.

## T3 — Interface `StorageProvider`

**Arquivo novo:** `services/storage/provider.py`
```python
from abc import ABC, abstractmethod

MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024


class StorageProviderError(Exception):
    """Erro genérico de provider de storage, tratado pelos handlers (nunca vaza cru ao usuário)."""


class StorageProvider(ABC):
    @abstractmethod
    async def upload(self, user_id: int, filename: str, file_bytes: bytes) -> str:
        """Persiste os bytes e retorna a chave de armazenamento."""

    @abstractmethod
    async def delete(self, key: str) -> None:
        """Remove o objeto identificado por `key`."""
```

**Teste** (`tests/services/storage/test_provider.py`, espelha `tests/services/llm/test_provider.py`):
- Uma subclasse concreta com os dois métodos implementados instancia normalmente.
- Instanciar `StorageProvider` diretamente levanta `TypeError`.

**Critério de aceitação:** os dois testes acima passam.

## T4 — `LocalStorageProvider`

**Arquivo novo:** `services/storage/local_provider.py`
```python
import os
import time

from services.storage.provider import StorageProvider

_BASE_DIR = "files"


class LocalStorageProvider(StorageProvider):
    async def upload(self, user_id: int, filename: str, file_bytes: bytes) -> str:
        os.makedirs(_BASE_DIR, exist_ok=True)
        key = f"{_BASE_DIR}/{user_id}-{int(time.time())}-{filename}"
        with open(key, "wb") as f:
            f.write(file_bytes)
        return key

    async def delete(self, key: str) -> None:
        if os.path.exists(key):
            os.remove(key)
```

**Teste** (`tests/services/storage/test_local_provider.py`, usar `tmp_path`/`monkeypatch.chdir` para isolar do repo real):
- `upload` grava os bytes no disco sob `files/` e retorna uma chave que existe no filesystem.
- `delete` remove o arquivo criado por `upload`.
- `delete` com uma chave inexistente não levanta exceção (idempotente).

**Critério de aceitação:** os três testes acima passam; nenhum arquivo sobra em `files/` após o teste (limpeza via `tmp_path`).

## T5 — `S3StorageProvider`

**Arquivo novo:** `services/storage/s3_provider.py`
```python
import time

import boto3

from services.storage.provider import StorageProvider, StorageProviderError


class S3StorageProvider(StorageProvider):
    def __init__(self, bucket_name: str, client=None):
        self._bucket_name = bucket_name
        self._client = client or boto3.client("s3")

    async def upload(self, user_id: int, filename: str, file_bytes: bytes) -> str:
        key = f"{user_id}/files/{int(time.time())}-{filename}"
        try:
            self._client.put_object(Bucket=self._bucket_name, Key=key, Body=file_bytes)
        except Exception as exc:
            raise StorageProviderError(f"falha ao enviar arquivo para S3: {exc}") from exc
        return key

    async def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket_name, Key=key)
```
Client injetável via construtor (`client=None`, testável sem monkeypatch) e chamada síncrona do boto3 dentro do método `async` — mesmo padrão já usado em `BedrockProvider` (`services/llm/bedrock_provider.py:56-57`), não introduzir `aioboto3` nem `run_in_executor`.

**Teste** (`tests/services/storage/test_s3_provider.py`, `client = Mock()` — mesmo padrão de `tests/services/llm/test_bedrock_provider.py`):
- `upload` chama `client.put_object` com `Bucket`, `Key` (contendo `user_id` e `filename`) e `Body=file_bytes`, e retorna a chave usada.
- `upload` quando `client.put_object` levanta exceção → propaga `StorageProviderError` (não a exceção crua do boto3).
- `delete` chama `client.delete_object` com `Bucket` e a `key` recebida.

**Critério de aceitação:** os três testes acima passam com client mockado — nenhuma chamada real à AWS em teste automatizado (regra do `CLAUDE.md`).

## T6 — Config e factory

**Arquivo:** `run_polling/config.py`

**Antes** (arquivo inteiro):
```python
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
# MEU_USER_ID = int(os.getenv("MEU_TELEGRAM_ID"))
```

**Depois** (acrescentar duas linhas, resto intocado):
```python
import os

from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
LLM_PROVIDER = os.getenv("LLM_PROVIDER", "gemini")
STORAGE_BACKEND = os.getenv("STORAGE_BACKEND", "local")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME", "guardiao-financeiro-files-dev-413948096391")
# MEU_USER_ID = int(os.getenv("MEU_TELEGRAM_ID"))
```

**Arquivo novo:** `services/storage/factory.py`
```python
from run_polling.config import S3_BUCKET_NAME, STORAGE_BACKEND
from services.storage.local_provider import LocalStorageProvider
from services.storage.provider import StorageProvider
from services.storage.s3_provider import S3StorageProvider


def get_storage_provider() -> StorageProvider:
    if STORAGE_BACKEND == "local":
        return LocalStorageProvider()
    if STORAGE_BACKEND == "s3":
        return S3StorageProvider(bucket_name=S3_BUCKET_NAME)
    raise ValueError(f"STORAGE_BACKEND inválido: {STORAGE_BACKEND!r} (esperado 'local' ou 's3')")
```

**Teste** (`tests/services/storage/test_factory.py`, espelha `tests/services/llm/test_factory.py`):
- `STORAGE_BACKEND="local"` (via `monkeypatch.setattr("services.storage.factory.STORAGE_BACKEND", "local")`) → retorna `LocalStorageProvider`.
- `STORAGE_BACKEND="s3"` → retorna `S3StorageProvider`.
- `STORAGE_BACKEND="outro"` → levanta `ValueError`.

**Critério de aceitação:** os três testes acima passam.

## T7 — Refatorar `ocr_service.py` para receber bytes diretamente

**Arquivo:** `services/ocr_service.py`

**Antes** (arquivo inteiro, já citado no INV003):
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

**Depois:**
```python
import sys

from models import Transacao
from services.llm.factory import get_llm_provider

_provider = get_llm_provider()


async def extract_document_data(file_bytes: bytes, mime_type: str) -> list[Transacao]:
    try:
        return await _provider.extract_document_transactions(file_bytes, mime_type)
    except Exception as exc:
        print(f"[ocr_service] falha ao extrair transação de documento: {exc}", file=sys.stderr)
        return []
```
Motivo: o mime-type e os bytes já chegam prontos do Telegram (via `Document.mime_type`/leitura em memória — T8/T9); a leitura de disco e a inferência por extensão eram só um artefato do fluxo antigo, não uma necessidade do `LLMProvider` (que sempre recebeu `file_bytes, mime_type`).

**Teste:** reescrever `tests/services/test_ocr_service.py` (atualmente usa `tmp_path`/`open` — apagar essa dependência):
```python
from datetime import date

from models import Transacao


def _fake_transacao() -> Transacao:
    return Transacao(
        data=date(2026, 7, 26),
        descricao="padaria",
        valor=15.0,
        tipo="saida",
        categoria="alimentacao",
    )


async def test_extract_document_data_returns_provider_result(monkeypatch):
    import services.ocr_service as ocr_service

    expected = [_fake_transacao()]

    class _FakeProvider:
        async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
            return expected

    monkeypatch.setattr(ocr_service, "_provider", _FakeProvider())

    result = await ocr_service.extract_document_data(b"fake-bytes", "image/jpeg")

    assert result == expected


async def test_extract_document_data_returns_empty_list_when_provider_raises(monkeypatch):
    import services.ocr_service as ocr_service

    class _FailingProvider:
        async def extract_document_transactions(self, file_bytes: bytes, mime_type: str) -> list[Transacao]:
            raise RuntimeError("falha inesperada")

    monkeypatch.setattr(ocr_service, "_provider", _FailingProvider())

    result = await ocr_service.extract_document_data(b"fake-bytes", "image/jpeg")

    assert result == []
```

**Critério de aceitação:** os dois testes passam; nenhum outro arquivo além de `handlers/photo_handler.py` e `handlers/pdf_handler.py` (T8/T9) referencia `extract_photo_data` (grep antes de finalizar).

## T8 — Refatorar `handlers/photo_handler.py`

**Antes** (já citado no INV003).

Além da migração pra storage, troca a mensagem de reconhecimento imediato (`"..."`, placeholder) por uma mensagem amigável, pedido do usuário nesta sessão: `"🔍 Recebi! Já vou dar uma olhada nisso..."` (mesma mensagem em `photo_handler.py` e `pdf_handler.py`, T9).

**Depois:**
```python
import sys

from services.message_service import format_message
from services.ocr_service import extract_document_data
from services.storage.factory import get_storage_provider
from services.storage.provider import MAX_FILE_SIZE_BYTES, StorageProviderError
from services.transaction_service import save_transactions

_storage = get_storage_provider()


async def get_photo(update, context):
    user_id = update.effective_user.id
    photo = update.message.photo[-1]

    if photo.file_size and photo.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text("Arquivo muito grande (máx. 20MB). Envie uma foto menor.")
        return

    file = await photo.get_file()
    await update.message.reply_text("🔍 Recebi! Já vou dar uma olhada nisso...")
    file_bytes = bytes(await file.download_as_bytearray())

    try:
        key = await _storage.upload(user_id, f"{photo.file_unique_id}.jpg", file_bytes)
    except StorageProviderError:
        await update.message.reply_text("Não consegui processar sua foto agora, tenta de novo.")
        return

    try:
        transactions = await extract_document_data(file_bytes, "image/jpeg")
    finally:
        try:
            await _storage.delete(key)
        except Exception as exc:
            print(f"[photo_handler] falha ao deletar {key} do storage: {exc}", file=sys.stderr)

    await save_transactions(transactions, user_id)
    message = format_message(transactions)
    await update.message.reply_text(message, parse_mode="HTML")
```
Pontos de erro conforme `plano-contexto.md` (Fase 2): falha de upload → responde e aborta antes de processar (arquivo que não persistiu não é processado); falha de delete → loga e segue (a lifecycle rule do bucket é a rede de segurança).

**Teste novo:** `tests/handlers/test_photo_handler.py` (pasta `tests/handlers/` ainda não existe no branch `main` — criar sem `__init__.py`, mesmo padrão de `tests/services/`). Mockar `update`/`context` (objetos `Mock`/`AsyncMock` com `effective_user.id`, `message.photo`, `message.reply_text`), `_storage` (`AsyncMock` do módulo `handlers.photo_handler`) e `extract_document_data` (monkeypatch). Cenários:
- Fluxo feliz: chama `_storage.upload`, depois `extract_document_data` com os bytes baixados e `"image/jpeg"`, depois `_storage.delete` com a chave retornada, e responde com `format_message`.
- `photo.file_size` acima de `MAX_FILE_SIZE_BYTES` → responde a mensagem de tamanho e **não** chama `get_file()`/`upload`.
- `_storage.upload` levanta `StorageProviderError` → responde mensagem de erro e **não** chama `extract_document_data`.

**Critério de aceitação:** os três cenários acima passam.

## T9 — Refatorar `handlers/pdf_handler.py`

**Antes** (já citado no INV003).

**Depois:**
```python
import sys

from telegram import Update

from services.message_service import format_message, split_message
from services.ocr_service import extract_document_data
from services.storage.factory import get_storage_provider
from services.storage.provider import MAX_FILE_SIZE_BYTES, StorageProviderError
from services.transaction_service import save_transactions

_storage = get_storage_provider()


async def get_pdf(update: Update, context):
    user_id = update.effective_user.id
    pdf = update.message.document

    if pdf.file_size and pdf.file_size > MAX_FILE_SIZE_BYTES:
        await update.message.reply_text("Arquivo muito grande (máx. 20MB). Envie um PDF menor.")
        return

    pdf_file = await pdf.get_file()
    await update.message.reply_text("🔍 Recebi! Já vou dar uma olhada nisso...")
    file_bytes = bytes(await pdf_file.download_as_bytearray())
    mime_type = pdf.mime_type or "application/pdf"

    try:
        key = await _storage.upload(user_id, pdf.file_name or f"{pdf.file_unique_id}.pdf", file_bytes)
    except StorageProviderError:
        await update.message.reply_text("Não consegui processar seu PDF agora, tenta de novo.")
        return

    try:
        transactions = await extract_document_data(file_bytes, mime_type)
    finally:
        try:
            await _storage.delete(key)
        except Exception as exc:
            print(f"[pdf_handler] falha ao deletar {key} do storage: {exc}", file=sys.stderr)

    await save_transactions(transactions, user_id)
    msg = format_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
```
Usa `pdf.mime_type` nativo do Telegram em vez de assumir `"application/pdf"` por extensão — com fallback pro literal, já que `Document.mime_type` é opcional na API do Telegram.

**Teste novo:** `tests/handlers/test_pdf_handler.py`, mesma estrutura de mocks do T8, cenários equivalentes (feliz, tamanho excedido, falha de upload). Adicionar um quarto cenário específico: `pdf.mime_type` ausente (`None`) → `extract_document_data` é chamado com `"application/pdf"` (fallback).

**Critério de aceitação:** os quatro cenários acima passam.

## T10 — `main.py`: remover criação incondicional de `fotos/`

**Antes** (linha 15): `os.makedirs("fotos", exist_ok=True)`.

**Depois:** remover a linha e o `import os` se ficar sem uso. `LocalStorageProvider.upload` já cria `files/` sob demanda (T4) — não há mais necessidade de preparar a pasta na inicialização, e o nome mudou de `fotos` para `files`.

**Critério de aceitação:** `main.py` não referencia mais `fotos/`; rodar o bot localmente com `STORAGE_BACKEND=local` (default) e mandar uma foto ainda funciona (cenário de teste manual abaixo).

## T11 — `docs/guardiao-financeiro-stack.yml`: rename + lifecycle rule

Quatro ocorrências de `MyDataBucket` (confirmadas por grep no INV003) mudam juntas:

**Antes** (linha 32-43):
```yaml
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

**Depois:**
```yaml
  MyFilesBucket:
    Type: AWS::S3::Bucket
    Properties:
      BucketName: !Sub 'guardiao-financeiro-files-${Environment}-${AWS::AccountId}'
      PublicAccessBlockConfiguration:
        BlockPublicAcls: true
        BlockPublicPolicy: true
        IgnorePublicAcls: true
        RestrictPublicBuckets: true
      BucketEncryption:
        ServerSideEncryptionConfiguration:
          - ServerSideEncryptionByDefault:
              SSEAlgorithm: AES256
      LifecycleConfiguration:
        Rules:
          - Id: ExpireObjectsAfterOneDay
            Status: Enabled
            ExpirationInDays: 1
```

Mais três renames pontuais (`MyDataBucket` → `MyFilesBucket`, sem outra mudança):
- Linha ~117: `Resource: !Sub '${MyDataBucket.Arn}/*'` → `Resource: !Sub '${MyFilesBucket.Arn}/*'`.
- Linha ~366: `BucketNome: !Ref MyDataBucket` → `BucketNome: !Ref MyFilesBucket`.
- Linha ~372 (Outputs): `Value: !Ref MyDataBucket` → `Value: !Ref MyFilesBucket`.

**Critério de aceitação:** `grep -n MyDataBucket docs/guardiao-financeiro-stack.yml` não retorna nada; `grep -n MyFilesBucket` retorna as mesmas 4 linhas (agora renomeadas). Este arquivo é referência arquitetural (não é deployado nesta fase — só na Fase 5, por princípio do plano), então não há teste automatizado aqui, só a conferência textual.

## T12 — Broadcast em `docs/PATTERNS.md`

Adicionar à seção "Decisões Estabelecidas" (mesmo estilo das entradas existentes):

```markdown
### Storage segue o mesmo padrão de troca de provedor externo (interface + factory + flag)

`StorageProvider` (`LocalStorageProvider`/`S3StorageProvider`, flag `STORAGE_BACKEND=local|s3`) reaplica o padrão já usado por `LLMProvider`/`LLM_PROVIDER`: interface ABC em `services/storage/`, implementações injetáveis via construtor (`client=None`, testável sem monkeypatch), factory que valida a flag e levanta `ValueError` em valor inválido. Confirma que a decisão "Troca de provedor externo" registrada acima vale, na prática, também para `storage`, não só para LLM — e reforça que `DB_BACKEND=sqlite|dynamo` (Fase 3) deve seguir o mesmo desenho em vez de redecidir do zero. Origem: `docs/analysis/INV003-fotos-para-s3.md` / `docs/tasks/TASKS005-fotos-para-s3.md`.
```

**Critério de aceitação:** entrada adicionada, sem alterar nenhuma outra seção do arquivo.

## Ordem de Execução

T1 e T2 podem ser feitos pelo usuário a qualquer momento (não bloqueiam o desenvolvimento com TDD, que usa client mockado) — mas são pré-requisito do cenário de teste manual com `STORAGE_BACKEND=s3` real. Ordem do código: T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12. T7 (ocr_service) precisa terminar antes de T8/T9, já que os handlers chamam a nova assinatura `extract_document_data(file_bytes, mime_type)`.

## Regra do Escoteiro / Testes

- TDD em todo T novo (T3-T9): teste vermelho antes do código, seguindo `superpowers:test-driven-development`.
- `pytest` na raiz deve passar 100% ao final, incluindo os testes já existentes (`tests/services/llm/`, `tests/test_prompts.py` etc.) — nenhum efeito colateral esperado neles.
- Nenhum teste automatizado chama S3/AWS real (regra do `CLAUDE.md`) — só client mockado (`Mock()`/`AsyncMock()`), igual ao padrão de `tests/services/llm/test_bedrock_provider.py`.
- `tests/handlers/` é uma pasta nova neste projeto (só existe hoje no worktree `feature/nlp-query-totals`, branch diferente) — seguir o mesmo padrão sem `__init__.py` usado em `tests/services/` e `tests/repository/`.

## Cenários de Teste Manual

1. **Local (default, sem AWS):** `STORAGE_BACKEND` não setado (default `local`). Rodar `python main.py`, mandar uma foto pequena → bot responde a transação extraída; conferir que o arquivo aparece e some de `files/` durante/depois do processamento.
2. **Local, PDF:** mesmo fluxo com um PDF real de extrato (o mesmo cenário 4 usado em `TASKS004`, que already exercised `maxTokens`).
3. **Arquivo grande demais:** mandar uma foto/documento acima de 20MB (ou simular com um arquivo dummy grande) → bot responde a mensagem de tamanho e não tenta baixar/processar.
4. **S3 real (depois de T1/T2 confirmados):** `STORAGE_BACKEND=s3` no `.env`, mandar foto e PDF → confirmar no console S3 (ou `aws s3 ls`) que o objeto aparece durante o processamento e some logo depois (delete pós-extração); conferir que a lifecycle rule está ativa (não depende de teste manual, já confirmada em T1).
5. **Rollback:** voltar `STORAGE_BACKEND=local` (ou remover a variável) com o bot rodando → volta a funcionar sem tocar em S3, confirmando que o flag realmente permite reverter.

## Fora de Escopo

- Remoção do `LocalStorageProvider` e do fallback `STORAGE_BACKEND=local` — só depois de dias de produção estável em `s3`, mesmo ciclo do `GeminiProvider` (Fase 1.7).
- Popular `.env.example` — o arquivo já está vazio hoje apesar de `BOT_TOKEN`/`LLM_PROVIDER`/`AWS_PROFILE` existirem em uso; não é uma lacuna introduzida por esta task, e populá-lo agora seria escopo não pedido.
- Deploy real do `docs/guardiao-financeiro-stack.yml` — o template continua sendo só referência arquitetural até a Fase 5.
- `s3:ListBucket` na IAM policy — não é necessário para `PutObject`/`GetObject`/`DeleteObject` por chave conhecida, e o plano não pede listagem nesta fase.
- Qualquer mudança no worktree `feature/nlp-query-totals` (Fase 6, branch separada).

## Validação Final

- [x] Bucket criado (T1) com lifecycle de 1 dia confirmada via CLI.
- [x] IAM policy ampliada (T2) e nova versão aplicada.
- [x] `services/storage/` completo (`provider.py`, `local_provider.py`, `s3_provider.py`, `factory.py`) com testes passando.
- [x] `ocr_service.extract_photo_data` não existe mais em nenhum lugar do código (grep limpo).
- [x] `photo_handler.py`/`pdf_handler.py` não fazem mais `download_to_drive`/`os.remove`/referência a `fotos/`.
- [x] `main.py` sem `os.makedirs("fotos", ...)`.
- [x] Mensagem de reconhecimento imediato trocada para `"🔍 Recebi! Já vou dar uma olhada nisso..."` em ambos os handlers.
- [x] `docs/guardiao-financeiro-stack.yml` sem nenhuma ocorrência de `MyDataBucket`.
- [x] `docs/PATTERNS.md` com a nova entrada de broadcast (+ 2 descobertas pós-implementação: `--import-mode=importlib` e profile admin vs. `guardiao-dev` em ações de bootstrap).
- [x] `pytest` 100% verde (45/45).
- [x] Cenários de Teste Manual 1, 2 e 4 executados (foto e PDF, local e S3 real — upload/delete confirmados manualmente). Cenário 3 (arquivo >20MB) e Cenário 5 (rollback) **não executados manualmente**, por decisão do usuário — a lógica do Cenário 3 já está coberta por teste automatizado mockado (T8/T9), e o Cenário 5 é apenas trocar a env var de volta para o default já testado no Cenário 1.
