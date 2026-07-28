---
type: TASKS
version: 1.2.0
author: Victor Veloso
date: 2026-07-27
status: Done
inv: docs/analysis/INV004-sqlite-para-dynamodb.md
spec: docs/specs/SPEC006-sqlite-para-dynamodb.md
plan: docs/plans/PLN006-sqlite-para-dynamodb.md
fase: "Fase 3 — docs/analysis/plano-contexto.md"
branch: feat/sqlite-para-dynamodb
---

## Progresso

- [x] T1 — Criar a tabela DynamoDB (ação manual do usuário)
- [x] T2 — Ampliar a IAM policy de desenvolvimento com DynamoDB
- [x] T3 — Config: `DB_BACKEND` e `DYNAMO_TABLE_NAME`
- [x] T4 — `repository/dedup.py` (funções puras)
- [x] T5 — `repository/provider.py` (contratos)
- [x] T6 — `repository/sqlite_repository.py` (substitui `repository/transaction.py`)
- [x] T7 — `repository/dynamo_repository.py`
- [x] T8 — `repository/config_repository.py`
- [x] T9 — `repository/factory.py`
- [x] T10 — `services/transaction_service.py`
- [x] T11 — `services/message_service.py`
- [x] T12 — Handlers: propagar o retorno de `save_transactions`
- [x] T13 — `main.py`: `init_db()` condicional
- [x] T14 — `scripts/migrate_sqlite_to_dynamo.py`
- [x] T15 — `scripts/seed_config.py`
- [x] T16 — Broadcast em `docs/PATTERNS.md`

# TASKS006 — Dados: SQLite → DynamoDB (+ modelagem de orçamento)

Diagnóstico completo em `INV004`, requisitos em `SPEC006`, estratégia técnica em `PLN006` — leitura obrigatória antes de qualquer código, junto com `CLAUDE.md` e `docs/PATTERNS.md`. Resumo do necessário para implementar:

`repository/transaction.py` hoje é uma classe concreta acoplada a `AsyncSession` (SQLAlchemy), sem interface, sem dedup, sem modelagem de configuração. Esta task dá a ele uma segunda implementação real (DynamoDB), reaplicando o padrão já estabelecido por `LLMProvider`/`StorageProvider` (ABC + implementações injetáveis + factory + flag `DB_BACKEND`), e fecha duas lacunas que nunca existiram em código algum: dedup determinística de 3 estados (NOVA/SUSPEITA/DUPLICATA_EXATA) e configuração de orçamento por usuário (baldes + dívida, mesmo *shape* de Item, campo `periodo` distingue).

**Branch:** `feat/sqlite-para-dynamodb`, nunca direto na `main`. Criar antes do T3 (T1/T2 são ações fora do código-fonte Python, podem rodar em paralelo).

## Decisões vinculantes (de `SPEC006`/`PLN006`, não redecidir aqui)

1. **Dedup:** `sortKey = "{data ISO}#{fingerprint}"`, `fingerprint = sha256(valor+tipo+descrição normalizada)[:16]`. Colisão de `sortKey` → **DUPLICATA_EXATA**, sempre bloqueia a inserção e nunca insere/descarta silenciosamente — mesmo em casos legítimos como duas compras idênticas no mesmo dia (decisão explícita do usuário, sem tratamento especial de adjacência). Sem colisão, mas com candidato dentro de 90 dias com `valor`/`tipo` iguais e descrição ≥ 0.8 de similaridade (`difflib.SequenceMatcher`) → **SUSPEITA**, insere mesmo assim, só sinaliza. Nenhuma chamada a LLM na classificação.
2. **UX de confirmação "sem estado":** a mensagem de resposta ao usuário avisa quando uma transação não foi salva por parecer duplicata e sugere reenviar com alguma diferença — sem fluxo de pergunta-e-espera-resposta, sem estado de conversa novo. Isso já resolve o "forçar gravação": a diferença no reenvio muda o fingerprint naturalmente.
3. **Configuração (orçamento) é um único tipo de Item** (`sortKey = "CONFIG#{nome}"`), campo `periodo` (`"mensal"` = balde recorrente, `"unico"` = dívida, nunca reseta). Sem schema separado para dívida. Saldo nunca é armazenado, sempre derivado de `get_totals_by_period`.
4. **`ConfigRepository` não tem ABC** — só uma implementação real (Dynamo), regra do `CLAUDE.md` ("nunca ABC sem segunda implementação real") continua valendo.
5. **`init_db()` (`database/connection.py`) não muda** — a chamada em `main.py` vira condicional a `DB_BACKEND == "sqlite"`.
6. **`batch_writer` não é usado** em nenhuma escrita desta task (transações ou migração) — `ConditionExpression` (necessária para dedup) não é suportada por `BatchWriteItem`. Todo `PutItem` de transação é individual e condicional.

## T1 — Criar a tabela DynamoDB (ação manual do usuário)

Por `PATTERNS.md` ("criação de recursos AWS é sempre ação manual", "bootstrap roda com profile admin, nunca `guardiao-dev`"), o Claude Code nunca roda este comando — só documenta aqui para o usuário executar.

```bash
aws dynamodb create-table \
  --table-name GuardiaoFinanceiro-Transacoes-dev \
  --attribute-definitions \
      AttributeName=userId,AttributeType=S \
      AttributeName=sortKey,AttributeType=S \
      AttributeName=categoria,AttributeType=S \
  --key-schema \
      AttributeName=userId,KeyType=HASH \
      AttributeName=sortKey,KeyType=RANGE \
  --global-secondary-indexes '[{
      "IndexName": "GSI-Categoria",
      "KeySchema": [
        {"AttributeName": "userId", "KeyType": "HASH"},
        {"AttributeName": "categoria", "KeyType": "RANGE"}
      ],
      "Projection": {"ProjectionType": "ALL"}
    }]' \
  --billing-mode PAY_PER_REQUEST \
  --region us-east-2
```

**Critério de aceitação:** `aws dynamodb describe-table --table-name GuardiaoFinanceiro-Transacoes-dev --region us-east-2` retorna `"TableStatus": "ACTIVE"` e mostra `GSI-Categoria` em `GlobalSecondaryIndexes`.

## T2 — Ampliar a IAM policy de desenvolvimento com DynamoDB

**Arquivo:** `scripts/aws/iam-policy-guardiao-dev.json` — Claude Code edita (é código no repo); o usuário roda os comandos AWS CLI depois.

**Depois** (adicionar este `Statement` ao array existente, sem tocar nos três já presentes — Bedrock ×2, S3):
```json
    {
      "Sid": "DynamoDBReadWriteTransacoesGuardiaoDev",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-2:413948096391:table/GuardiaoFinanceiro-Transacoes-dev",
        "arn:aws:dynamodb:us-east-2:413948096391:table/GuardiaoFinanceiro-Transacoes-dev/index/*"
      ]
    }
```

Comando para o usuário rodar após o commit (mesma mecânica de `TASKS005` T2, nova *policy version*):
```bash
aws iam create-policy-version \
  --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock \
  --policy-document file://scripts/aws/iam-policy-guardiao-dev.json \
  --set-as-default
```

> **Correção (v1.1.0):** a versão original deste comando incluía `--profile guardiao-dev`, o que causa `AccessDenied` — `iam:CreatePolicyVersion` é ação de bootstrap de conta, não permissão de runtime do usuário `guardiao-financeiro-dev`. Mesma classe de erro já documentada em `PATTERNS.md` ("Bootstrap de conta roda com o profile admin, nunca com `guardiao-dev`"), originada em `TASKS005` T1. Corrigido para usar o profile default (identidade pessoal do usuário) do AWS CLI, sem `--profile`. Descoberto na execução real desta task.

**Critério de aceitação:** `aws iam get-policy-version --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock --version-id <nova-versao> --profile guardiao-dev` mostra o `Sid` `DynamoDBReadWriteTransacoesGuardiaoDev`.

## T3 — Config: `DB_BACKEND` e `DYNAMO_TABLE_NAME`

**Arquivo:** `run_polling/config.py`

**Antes** (arquivo inteiro):
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

**Depois** (acrescentar duas linhas, resto intocado):
```python
DB_BACKEND = os.getenv("DB_BACKEND", "sqlite")
DYNAMO_TABLE_NAME = os.getenv("DYNAMO_TABLE_NAME", "GuardiaoFinanceiro-Transacoes-dev")
```

**Critério de aceitação:** `from run_polling.config import DB_BACKEND, DYNAMO_TABLE_NAME` funciona; default `DB_BACKEND == "sqlite"` preserva o comportamento atual sem exigir nenhuma env var nova.

## T4 — `repository/dedup.py` (funções puras)

**Arquivo novo:**
```python
import hashlib
import re
import unicodedata
from difflib import SequenceMatcher

SIMILARITY_THRESHOLD = 0.8
SUSPECT_WINDOW_DAYS = 90


def normalize_description(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s]", "", text.lower())
    return re.sub(r"\s+", " ", text).strip()


def compute_fingerprint(valor: float, tipo: str, descricao_normalizada: str) -> str:
    raw = f"{valor:.2f}|{tipo}|{descricao_normalizada}"
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_similar(a: str, b: str) -> bool:
    return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD
```

**Teste** (`tests/repository/test_dedup.py`):
- `normalize_description("Café  com Açúcar!!")` → `"cafe com acucar"` (minúsculas, sem acento, sem pontuação, espaços colapsados).
- `compute_fingerprint` é determinística: mesma entrada → mesma saída, sempre.
- `compute_fingerprint` muda se `valor`, `tipo` ou `descricao_normalizada` mudam (3 casos, um por campo).
- `is_similar("cafe padaria", "cafe padaria")` → `True`; `is_similar("cafe padaria", "uber viagem")` → `False`; um caso de ruído leve de OCR (ex. `"cafe padaria centro"` vs `"cafe padria centro"`) → `True` (dentro do threshold 0.8).

**Critério de aceitação:** todos os testes acima passam. Módulo não importa nada de `boto3`/SQLAlchemy — 100% puro.

## T5 — `repository/provider.py` (contratos)

**Arquivo novo:**
```python
from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from models import Transacao


class RepositoryError(Exception):
    """Erro genérico de repository, tratado pelos services (nunca vaza driver nativo)."""


class TransactionSaveResult(BaseModel):
    transacao: Transacao
    status: Literal["nova", "suspeita", "duplicata_exata"]
    similares: list[Transacao] = []


class ConfigItem(BaseModel):
    nome: str
    teto: float
    periodo: Literal["mensal", "unico"]
    rollover: bool = False
    data_limite: date | None = None
    created_at: datetime
    updated_at: datetime


class TransactionRepository(ABC):
    @abstractmethod
    async def save_transactions(
        self, transactions: list[Transacao], telegram_user_id: int
    ) -> list[TransactionSaveResult]: ...

    @abstractmethod
    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]: ...

    @abstractmethod
    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]: ...
```

**Teste** (`tests/repository/test_provider.py`, espelha `tests/services/llm/test_provider.py`):
- Uma subclasse concreta com os três métodos implementados instancia normalmente.
- Instanciar `TransactionRepository` diretamente levanta `TypeError`.
- `TransactionSaveResult`/`ConfigItem` aceitam os campos esperados e rejeitam `status`/`periodo` fora do `Literal` (`pydantic.ValidationError`).

**Critério de aceitação:** os testes acima passam.

## T6 — `repository/sqlite_repository.py` (substitui `repository/transaction.py`)

**Antes** (`repository/transaction.py`, arquivo a remover — só tinha `save_transactions`/`find_by_user`, sem dedup, sessão injetada no construtor).

**Depois** (arquivo novo `repository/sqlite_repository.py`):
```python
from datetime import date, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.connection import async_session
from database.entities.transaction import TransactionEntity
from models import Transacao
from repository.dedup import (
    SUSPECT_WINDOW_DAYS,
    compute_fingerprint,
    is_similar,
    normalize_description,
)
from repository.provider import TransactionRepository, TransactionSaveResult


def _to_transacao(e: TransactionEntity) -> Transacao:
    return Transacao(
        data=e.data, descricao=e.descricao, valor=e.valor, tipo=e.tipo, categoria=e.categoria
    )


class SqliteTransactionRepository(TransactionRepository):
    def __init__(self, session_factory=None):
        self._session_factory = session_factory or async_session

    async def save_transactions(
        self, transactions: list[Transacao], telegram_user_id: int
    ) -> list[TransactionSaveResult]:
        results = []
        async with self._session_factory() as session:
            for t in transactions:
                results.append(await self._save_one(session, t, telegram_user_id))
            await session.commit()
        return results

    async def _save_one(
        self, session: AsyncSession, t: Transacao, telegram_user_id: int
    ) -> TransactionSaveResult:
        descricao_norm = normalize_description(t.descricao)
        fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)

        same_day = await session.execute(
            select(TransactionEntity).where(
                TransactionEntity.telegram_user_id == telegram_user_id,
                TransactionEntity.data == t.data,
            )
        )
        for candidate in same_day.scalars().all():
            candidate_fp = compute_fingerprint(
                candidate.valor, candidate.tipo, normalize_description(candidate.descricao)
            )
            if candidate_fp == fingerprint:
                return TransactionSaveResult(transacao=t, status="duplicata_exata")

        window_start = t.data - timedelta(days=SUSPECT_WINDOW_DAYS)
        window_end = t.data + timedelta(days=SUSPECT_WINDOW_DAYS)
        window = await session.execute(
            select(TransactionEntity).where(
                TransactionEntity.telegram_user_id == telegram_user_id,
                TransactionEntity.data >= window_start,
                TransactionEntity.data <= window_end,
                TransactionEntity.valor == t.valor,
                TransactionEntity.tipo == t.tipo,
            )
        )
        similares = [
            _to_transacao(c)
            for c in window.scalars().all()
            if is_similar(normalize_description(c.descricao), descricao_norm)
        ]

        session.add(TransactionEntity(
            telegram_user_id=telegram_user_id,
            data=t.data, descricao=t.descricao, valor=t.valor, tipo=t.tipo, categoria=t.categoria,
        ))

        if similares:
            return TransactionSaveResult(transacao=t, status="suspeita", similares=similares)
        return TransactionSaveResult(transacao=t, status="nova")

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TransactionEntity).where(
                    TransactionEntity.telegram_user_id == telegram_user_id
                )
            )
            return [_to_transacao(e) for e in result.scalars().all()]

    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(TransactionEntity.tipo, func.sum(TransactionEntity.valor))
                .where(
                    TransactionEntity.telegram_user_id == telegram_user_id,
                    TransactionEntity.data >= start,
                    TransactionEntity.data <= end,
                )
                .group_by(TransactionEntity.tipo)
            )
            key_map = {"entrada": "entradas", "saida": "saidas"}
            totals = {"entradas": 0.0, "saidas": 0.0}
            for tipo, total in result.all():
                key = key_map.get(tipo)
                if key:
                    totals[key] = total or 0.0
            return totals
```
`get_totals_by_period` é o método já existente em `feature/nlp-query-totals` (`repository/transaction.py`), portado aqui sem alteração de lógica — só de localização (decisão do usuário, `INV004`).

**Teste** (`tests/repository/test_sqlite_repository.py`, usar a fixture `db_session`/`session_factory` em memória — mesmo padrão de `tests/repository/test_transaction.py` já existente no worktree `feature/nlp-query-totals`, adaptado para `session_factory` em vez de `session` direto):
- Duas transações idênticas (mesma `data`, `valor`, `tipo`, `descricao`) inseridas em sequência: a primeira → `"nova"`; a segunda → `"duplicata_exata"`, e só uma linha existe na tabela ao final (`find_by_user` retorna 1 item).
- Duas transações com `valor`/`tipo` iguais, descrição com pequena variação (ex. `"padaria"` vs `"padaria centro"`), dentro de 90 dias: a segunda → `"suspeita"`, `similares` contém a primeira, **e ambas existem na tabela** (`find_by_user` retorna 2 itens).
- Transação sem nenhum candidato próximo → `"nova"`.
- Café R$8, bolo R$10, café R$8 no mesmo dia (mesmo `userId`): o segundo café → `"duplicata_exata"` mesmo com o bolo no meio (confirma B3b do SPEC — sem tratamento de adjacência).
- `get_totals_by_period`: os 4 testes já existentes em `tests/repository/test_transaction.py` (worktree `feature/nlp-query-totals`) portados aqui, mesmos cenários (soma por tipo, ignora outro usuário, ignora fora do range, zera sem transações).
- `find_by_user` continua funcionando como hoje (teste de regressão simples).

**Critério de aceitação:** todos os testes acima passam; `repository/transaction.py` é removido do repositório (nenhuma referência sobrando — `grep -rn "repository.transaction" --include="*.py" .` limpo, exceto o path do próprio arquivo antigo que deixa de existir).

## T7 — `repository/dynamo_repository.py`

**Arquivo novo:**
```python
import sys
from datetime import date
from decimal import Decimal

import boto3
from boto3.dynamodb.conditions import Key
from botocore.exceptions import ClientError

from models import Transacao
from repository.dedup import (
    SUSPECT_WINDOW_DAYS,
    compute_fingerprint,
    is_similar,
    normalize_description,
)
from repository.provider import RepositoryError, TransactionRepository, TransactionSaveResult

_HIGH_SENTINEL = "￿"


def _item_to_transacao(item: dict) -> Transacao:
    return Transacao(
        data=date.fromisoformat(item["data"]),
        descricao=item["descricao"],
        valor=float(item["valor"]),
        tipo=item["tipo"],
        categoria=item.get("categoria", ""),
    )


class DynamoTransactionRepository(TransactionRepository):
    def __init__(self, table_name: str, resource=None):
        self._table = (resource or boto3.resource("dynamodb", region_name="us-east-2")).Table(table_name)

    async def save_transactions(
        self, transactions: list[Transacao], telegram_user_id: int
    ) -> list[TransactionSaveResult]:
        return [await self._save_one(t, telegram_user_id) for t in transactions]

    async def _save_one(self, t: Transacao, telegram_user_id: int) -> TransactionSaveResult:
        descricao_norm = normalize_description(t.descricao)
        fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)
        sort_key = f"{t.data.isoformat()}#{fingerprint}"
        user_id = str(telegram_user_id)

        item = {
            "userId": user_id,
            "sortKey": sort_key,
            "data": t.data.isoformat(),
            "descricao": t.descricao,
            "valor": Decimal(str(t.valor)),
            "tipo": t.tipo,
        }
        if t.categoria:
            item["categoria"] = t.categoria
        try:
            self._table.put_item(
                Item=item,
                ConditionExpression="attribute_not_exists(sortKey)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return TransactionSaveResult(transacao=t, status="duplicata_exata")
            raise RepositoryError(f"falha ao gravar transação no DynamoDB: {exc}") from exc

        similares = await self._find_similar(user_id, t, descricao_norm, exclude_sort_key=sort_key)
        if similares:
            return TransactionSaveResult(transacao=t, status="suspeita", similares=similares)
        return TransactionSaveResult(transacao=t, status="nova")

    async def _find_similar(
        self, user_id: str, t: Transacao, descricao_norm: str, exclude_sort_key: str
    ) -> list[Transacao]:
        from datetime import timedelta
        start = (t.data - timedelta(days=SUSPECT_WINDOW_DAYS)).isoformat()
        end = (t.data + timedelta(days=SUSPECT_WINDOW_DAYS)).isoformat()
        try:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("userId").eq(user_id) & Key("sortKey").between(f"{start}#", f"{end}#{_HIGH_SENTINEL}")
                )
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar candidatos de SUSPEITA: {exc}") from exc

        similares = []
        for item in response.get("Items", []):
            if item["sortKey"] == exclude_sort_key:
                # o item recém-gravado por esta própria chamada já está visível na
                # Query (put_item já commitou antes de chegarmos aqui) — sem essa
                # exclusão, toda transação "nova" se compararia contra si mesma
                # (similaridade 1.0) e seria classificada como "suspeita".
                continue
            if float(item["valor"]) != t.valor or item["tipo"] != t.tipo:
                continue
            if is_similar(normalize_description(item["descricao"]), descricao_norm):
                similares.append(_item_to_transacao(item))
        return similares

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        try:
            response = self._table.query(KeyConditionExpression=Key("userId").eq(str(telegram_user_id)))
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar transações do usuário: {exc}") from exc
        return [
            _item_to_transacao(item)
            for item in response.get("Items", [])
            if not item["sortKey"].startswith("CONFIG#")
        ]

    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]:
        try:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("userId").eq(str(telegram_user_id))
                    & Key("sortKey").between(f"{start.isoformat()}#", f"{end.isoformat()}#{_HIGH_SENTINEL}")
                )
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar totais por período: {exc}") from exc

        totals = {"entradas": 0.0, "saidas": 0.0}
        key_map = {"entrada": "entradas", "saida": "saidas"}
        for item in response.get("Items", []):
            if item["sortKey"].startswith("CONFIG#"):
                continue
            key = key_map.get(item.get("tipo"))
            if key:
                totals[key] += float(item["valor"])
        return totals
```
`Decimal(str(valor))` (nunca `Decimal(valor)` direto de um `float`) evita erro de precisão binária do `Decimal` — gotcha documentado em `PLN006`, seção Riscos. `_HIGH_SENTINEL` resolve o range de `Query` sobre `sortKey` composto (mesmo risco). `find_by_user` filtra Items de configuração (`sortKey` começando com `CONFIG#`) para não misturar com transações — mesma tabela, tipos de Item diferentes.

> **Correção (v1.2.0):** a versão original sempre incluía `"categoria": t.categoria` no Item, mesmo quando `t.categoria == ""` (default de `Transacao.categoria`, comum quando a extração via LLM não detecta categoria). DynamoDB rejeita com `ValidationException` qualquer `PutItem` cujo valor de atributo-chave de uma GSI (aqui, `categoria` é a range key de `GSI-Categoria`) seja string vazia — "The AttributeValue for a key attribute cannot contain an empty string value". Corrigido para omitir o atributo `categoria` do Item quando vazio, em vez de gravar `""` — padrão documentado da AWS para GSIs esparsas: um Item sem o atributo-chave simplesmente não aparece naquele índice, sem erro. `find_by_user`/`get_totals_by_period` já usam `item.get("categoria", "")` na leitura, compatível sem mudança. Descoberto em teste manual real (Cenário 4, envio de foto) — não coberto pelos testes mockados originais de T7 porque o mock de teste sempre usava `categoria` não vazia.

**Teste** (`tests/repository/test_dynamo_repository.py`, `resource = Mock()` com `resource.Table.return_value = Mock()` — mesmo padrão de `tests/services/llm/test_bedrock_provider.py`/`test_s3_provider.py`, **sem chamada real à AWS**):
- `save_transactions` com `put_item` bem-sucedido: o mock de `query` retorna **o próprio Item recém-gravado** (`Items: [item_com_o_mesmo_sortKey_calculado]`) — simula o que uma `Query` real mostraria, já que o `put_item` já commitou antes da busca de SUSPEITA rodar. Resultado esperado: `status="nova"` (o item se exclui da comparação por `sortKey` igual — regressão direta do bug "toda transação nova vira suspeita de si mesma", corrigido em `_find_similar`).
- `put_item` levanta `ClientError` com `Code="ConditionalCheckFailedException"` → `status="duplicata_exata"`, `query` (busca de SUSPEITA) **não é chamado**.
- `put_item` bem-sucedido, `query` retorna o próprio Item recém-gravado **mais** um segundo Item de `sortKey` diferente, com `valor`/`tipo` iguais e descrição similar → `status="suspeita"`, `similares` contém só o segundo Item (o próprio continua excluído).
- `put_item` levanta `ClientError` com outro código (ex. `"ValidationException"`) → propaga `RepositoryError`, não `ConditionalCheckFailedException`.
- **Paridade com T6 (B7 do SPEC):** café R$8, bolo R$10, café R$8 (três chamadas de `save_transactions`, cada uma com seu próprio mock de `put_item`/`query` simulando o estado acumulado da tabela) — o segundo café colide no `sortKey` do primeiro (mesmo fingerprint) → `ConditionalCheckFailedException` → `status="duplicata_exata"`, mesmo resultado que `SqliteTransactionRepository` produz no teste equivalente de T6, mesmo com o bolo no meio.
- `find_by_user` chama `query` com `KeyConditionExpression` filtrando por `userId`, e items com `sortKey` iniciando em `"CONFIG#"` são excluídos do resultado.
- `get_totals_by_period` soma `entradas`/`saidas` corretamente a partir de Items mockados (excluindo Items com `sortKey` iniciando em `"CONFIG#"`, mesmo filtro de `find_by_user`), e usa `Key(...).between(...)` com o sentinela `￿` no limite superior (assert no `call_args` do mock).

**Critério de aceitação:** todos os testes acima passam com `resource`/`table` mockados — nenhuma chamada real a AWS em teste automatizado.

## T8 — `repository/config_repository.py`

**Arquivo novo:**
```python
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

import boto3
from botocore.exceptions import ClientError

from repository.provider import ConfigItem, RepositoryError


def _item_to_config(item: dict) -> ConfigItem:
    return ConfigItem(
        nome=item["nome"],
        teto=float(item["teto"]),
        periodo=item["periodo"],
        rollover=item.get("rollover", False),
        data_limite=date.fromisoformat(item["dataLimite"]) if item.get("dataLimite") else None,
        created_at=datetime.fromisoformat(item["createdAt"]),
        updated_at=datetime.fromisoformat(item["updatedAt"]),
    )


class ConfigRepository:
    def __init__(self, table_name: str, resource=None):
        self._table = (resource or boto3.resource("dynamodb", region_name="us-east-2")).Table(table_name)

    async def save_config(
        self,
        telegram_user_id: int,
        nome: str,
        teto: float,
        periodo: Literal["mensal", "unico"],
        rollover: bool = False,
        data_limite: date | None = None,
    ) -> None:
        now = datetime.now().isoformat()
        item = {
            "userId": str(telegram_user_id),
            "sortKey": f"CONFIG#{nome.lower()}",
            "nome": nome,
            "teto": Decimal(str(teto)),
            "periodo": periodo,
            "rollover": rollover,
            "createdAt": now,
            "updatedAt": now,
        }
        if data_limite:
            item["dataLimite"] = data_limite.isoformat()
        try:
            self._table.put_item(Item=item)
        except ClientError as exc:
            raise RepositoryError(f"falha ao gravar configuração: {exc}") from exc

    async def get_config(self, telegram_user_id: int, nome: str) -> ConfigItem | None:
        try:
            response = self._table.get_item(
                Key={"userId": str(telegram_user_id), "sortKey": f"CONFIG#{nome.lower()}"}
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao ler configuração: {exc}") from exc
        item = response.get("Item")
        return _item_to_config(item) if item else None

    async def list_configs(self, telegram_user_id: int) -> list[ConfigItem]:
        from boto3.dynamodb.conditions import Key
        try:
            response = self._table.query(
                KeyConditionExpression=Key("userId").eq(str(telegram_user_id))
                & Key("sortKey").begins_with("CONFIG#")
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao listar configurações: {exc}") from exc
        return [_item_to_config(item) for item in response.get("Items", [])]
```
`save_config` sobrescreve (`put_item` sem `ConditionExpression`) — atualizar um balde existente é o caso comum (mudar o teto), não precisa de proteção contra sobrescrita como as transações.

**Teste** (`tests/repository/test_config_repository.py`, `resource` mockado):
- `save_config` com `periodo="mensal"` chama `put_item` com `Item["periodo"] == "mensal"` e sem `dataLimite`.
- `save_config` com `periodo="unico"` e `data_limite` informado inclui `dataLimite` no Item.
- `get_config` quando o Item não existe (`response = {}`) retorna `None`.
- `get_config` quando existe retorna um `ConfigItem` com os campos convertidos (`teto` como `float`, não `Decimal`).
- `list_configs` chama `query` com `begins_with("CONFIG#")`.

**Critério de aceitação:** todos os testes acima passam com client/table mockados.

## T9 — `repository/factory.py`

**Arquivo novo:**
```python
from run_polling.config import DB_BACKEND, DYNAMO_TABLE_NAME
from repository.dynamo_repository import DynamoTransactionRepository
from repository.provider import TransactionRepository
from repository.sqlite_repository import SqliteTransactionRepository


def get_transaction_repository() -> TransactionRepository:
    if DB_BACKEND == "sqlite":
        return SqliteTransactionRepository()
    if DB_BACKEND == "dynamo":
        return DynamoTransactionRepository(table_name=DYNAMO_TABLE_NAME)
    raise ValueError(f"DB_BACKEND inválido: {DB_BACKEND!r} (esperado 'sqlite' ou 'dynamo')")
```

**Teste** (`tests/repository/test_factory.py`, espelha `tests/services/llm/test_factory.py`):
- `DB_BACKEND="sqlite"` (via `monkeypatch.setattr("repository.factory.DB_BACKEND", "sqlite")`) → retorna `SqliteTransactionRepository`.
- `DB_BACKEND="dynamo"` → retorna `DynamoTransactionRepository`.
- `DB_BACKEND="outro"` → levanta `ValueError`.

**Critério de aceitação:** os três testes acima passam.

## T10 — `services/transaction_service.py`

**Antes** (arquivo inteiro, já citado no INV004).

**Depois:**
```python
from datetime import date

from models import Transacao
from repository.factory import get_transaction_repository
from repository.provider import ConfigItem, TransactionSaveResult


async def save_transactions(transactions: list[Transacao], telegram_user_id: int) -> list[TransactionSaveResult]:
    repository = get_transaction_repository()
    return await repository.save_transactions(transactions, telegram_user_id)


async def get_transactions(telegram_user_id: int) -> list[Transacao]:
    repository = get_transaction_repository()
    return await repository.find_by_user(telegram_user_id)


async def get_totals(telegram_user_id: int, start: date, end: date) -> dict[str, float]:
    repository = get_transaction_repository()
    return await repository.get_totals_by_period(telegram_user_id, start, end)
```
`get_totals` é o método já existente em `feature/nlp-query-totals`, portado (mesma assinatura). `async_session`/`TransactionRepository(session)` somem daqui — a sessão vira responsabilidade interna de `SqliteTransactionRepository` (T6).

**Teste** (`tests/services/test_transaction_service.py`, `monkeypatch` de `services.transaction_service.get_transaction_repository` retornando um repository fake/`AsyncMock`):
- `save_transactions` chama `repository.save_transactions` com os argumentos recebidos e retorna o resultado sem transformação.
- `get_transactions`/`get_totals` equivalentes.

**Critério de aceitação:** os testes acima passam.

## T11 — `services/message_service.py`

**Antes** (`format_message(transactions: list[Transacao]) -> str`, já citado no INV004/PLN006).

**Depois:**
```python
from repository.provider import TransactionSaveResult


def format_message(results: list[TransactionSaveResult]) -> str:
    if not results:
        return "Não encontrei nenhuma transação nessa imagem."

    lines = ["<b>📊 Extrato processado</b>", ""]
    income_total = 0.0
    expense_total = 0.0

    for r in results:
        t = r.transacao
        if r.status == "duplicata_exata":
            lines.append(
                f"⚠️ {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f} "
                "(não salva, já registrada — reenvie com alguma diferença se for uma compra real)"
            )
            continue

        emoji = "🟡" if r.status == "suspeita" else ("🟢" if t.tipo == "entrada" else "🔴")
        if t.tipo == "entrada":
            income_total += t.valor
        else:
            expense_total += t.valor
        note = " (parece semelhante a uma já registrada)" if r.status == "suspeita" else ""
        lines.append(f"{emoji} {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}{note}")

    balance = income_total - expense_total
    lines.append("")
    lines.append("<b>Resumo</b>")
    lines.append(f"🟢 Entradas: R$ {income_total:.2f}")
    lines.append(f"🔴 Saídas: R$ {expense_total:.2f}")
    lines.append(f"💰 Saldo: R$ {balance:.2f}")

    return "\n".join(lines)
```
`split_message` (mesmo arquivo) não muda — continua operando sobre a `str` final.

**Teste** (`tests/services/test_message_service.py`, criar/atualizar):
- Lista vazia → mensagem "não encontrei nenhuma transação".
- Só `"nova"` → totais batem com o comportamento atual (teste de regressão).
- Um resultado `"duplicata_exata"` → aparece com `⚠️`, **não** entra nos totais.
- Um resultado `"suspeita"` → aparece com `🟡` e a nota, **entra** nos totais (SPEC critério 2: SUSPEITA não bloqueia).

**Critério de aceitação:** os quatro cenários acima passam.

## T12 — Handlers: propagar o retorno de `save_transactions`

**Arquivos:** `handlers/text_handler.py`, `handlers/photo_handler.py`, `handlers/pdf_handler.py` — uma linha muda em cada.

**Antes** (`text_handler.py`, trecho):
```python
    await save_transactions(transactions, user_id)
    msg = format_message(transactions)
```

**Depois:**
```python
    results = await save_transactions(transactions, user_id)
    msg = format_message(results)
```
Mesma mudança (`results = await save_transactions(...)` seguido de `format_message(results)`) em `photo_handler.py` e `pdf_handler.py`, sem tocar em mais nada desses arquivos (upload/delete de storage, checagem de tamanho — tudo intocado, Fase 2).

**Teste:** atualizar os mocks existentes em `tests/handlers/test_photo_handler.py`/`test_pdf_handler.py` (já existem, criados na Fase 2) para que `save_transactions` (mockado) retorne `list[TransactionSaveResult]` em vez de `None`, e `format_message` seja chamado com esse retorno. `tests/handlers/test_text_handler.py` não existe ainda na `main` — criar seguindo o mesmo padrão dos outros dois (mock de `update`/`context`, `extract_text_transactions`, `save_transactions`), cobrindo: fluxo feliz (chama `format_message` com o retorno de `save_transactions`) e mensagem "nenhuma transação identificada" quando a extração retorna lista vazia.

**Critério de aceitação:** todos os testes de handlers passam com os mocks atualizados.

## T13 — `main.py`: `init_db()` condicional

**Antes** (linha 13): `asyncio.run(init_db())` incondicional.

**Depois:**
```python
from run_polling.config import BOT_TOKEN, DB_BACKEND
from database.connection import init_db


def main():
    if DB_BACKEND == "sqlite":
        asyncio.run(init_db())
    ...
```

**Critério de aceitação:** com `DB_BACKEND=dynamo`, rodar `python main.py` não tenta criar/abrir `guardiao.db` (nenhum arquivo `.db` novo aparece na raiz do projeto).

## T14 — `scripts/migrate_sqlite_to_dynamo.py`

**Arquivo novo** (script standalone, roda fora do bot):
```python
import asyncio

from database.connection import async_session
from database.entities.transaction import TransactionEntity
from models import Transacao
from repository.dynamo_repository import DynamoTransactionRepository
from run_polling.config import DYNAMO_TABLE_NAME
from sqlalchemy import select


async def migrate() -> None:
    dynamo_repo = DynamoTransactionRepository(table_name=DYNAMO_TABLE_NAME)
    read_count = 0
    written_count = 0

    async with async_session() as session:
        result = await session.execute(select(TransactionEntity))
        entities = result.scalars().all()

    dropped = []
    for e in entities:
        read_count += 1
        t = Transacao(data=e.data, descricao=e.descricao, valor=e.valor, tipo=e.tipo, categoria=e.categoria)
        results = await dynamo_repo.save_transactions([t], e.telegram_user_id)
        if results[0].status != "duplicata_exata":
            written_count += 1
        else:
            dropped.append(t)

    print(f"Linhas lidas do SQLite: {read_count}")
    print(f"Items gravados no DynamoDB: {written_count}")
    if dropped:
        print(f"Diferença: {len(dropped)} linha(s) já existiam no DynamoDB (duplicata_exata, ignoradas):")
        for t in dropped:
            print(f"  - {t.data.isoformat()} | {t.tipo} | R$ {t.valor:.2f} | {t.descricao}")


if __name__ == "__main__":
    asyncio.run(migrate())
```
Reaproveita `DynamoTransactionRepository.save_transactions` (mesma checagem condicional item a item, D1/D3 do SPEC — nunca `batch_writer`, nunca abre `guardiao.db` em modo escrita). Idempotente: rodar duas vezes não duplica.

**Teste** (`tests/scripts/test_migrate_sqlite_to_dynamo.py`, `DynamoTransactionRepository` mockada via monkeypatch — sem AWS real, seguindo a regra do `CLAUDE.md`):
- Com N entities no banco de teste (fixture em memória) e `save_transactions` mockado sempre retornando `status="nova"`, o script reporta `read_count == written_count == N`.
- Com uma entity cujo mock retorna `status="duplicata_exata"`, `written_count == N - 1` e a mensagem de diferença aparece.

**Critério de aceitação:** os dois testes acima passam. Execução real contra AWS é cenário de teste manual (abaixo), não automatizado.

## T15 — `scripts/seed_config.py`

**Arquivo novo** (script administrativo simples, sem interação de chat — SPEC C4):
```python
import asyncio
import sys
from datetime import date

from repository.config_repository import ConfigRepository
from run_polling.config import DYNAMO_TABLE_NAME


async def seed(user_id: int, nome: str, teto: float, periodo: str, rollover: bool, data_limite: str | None) -> None:
    repo = ConfigRepository(table_name=DYNAMO_TABLE_NAME)
    await repo.save_config(
        telegram_user_id=user_id,
        nome=nome,
        teto=teto,
        periodo=periodo,
        rollover=rollover,
        data_limite=date.fromisoformat(data_limite) if data_limite else None,
    )
    print(f"Configuração '{nome}' gravada para o usuário {user_id} (periodo={periodo}, teto={teto}).")


if __name__ == "__main__":
    # uso: python scripts/seed_config.py <user_id> <nome> <teto> <mensal|unico> [rollover=true|false] [data_limite=YYYY-MM-DD]
    user_id = int(sys.argv[1])
    nome = sys.argv[2]
    teto = float(sys.argv[3])
    periodo = sys.argv[4]
    rollover = len(sys.argv) > 5 and sys.argv[5].lower() == "true"
    data_limite = sys.argv[6] if len(sys.argv) > 6 else None
    asyncio.run(seed(user_id, nome, teto, periodo, rollover, data_limite))
```

**Teste:** nenhum teste automatizado dedicado — é um script fino sobre `ConfigRepository`, já coberto por `test_config_repository.py` (T8). Validação é o cenário de teste manual abaixo.

**Critério de aceitação:** script roda sem erro de sintaxe/import (`python -c "import scripts.seed_config"` ou equivalente); uso real é cenário manual.

## T16 — Broadcast em `docs/PATTERNS.md`

Adicionar à seção "Decisões Estabelecidas":

```markdown
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
```

**Critério de aceitação:** as cinco entradas adicionadas, sem alterar nenhuma seção existente do arquivo.

## Ordem de Execução

T1 e T2 (ações AWS) podem rodar em paralelo com o código a qualquer momento — só bloqueiam os Cenários de Teste Manual com Dynamo real, não o desenvolvimento (TDD usa client mockado). Ordem do código: T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10 → T11 → T12 → T13 → T14 → T15 → T16. T4/T5 não têm dependência entre si (podem ser feitos em qualquer ordem relativa), mas ambos precisam existir antes de T6/T7. T10-T12 são estritamente sequenciais (cada um depende do contrato do anterior).

## Regra do Escoteiro / Testes

- TDD em todo T novo com lógica pura ou mockável (T4-T12, T14): teste vermelho antes do código, seguindo `superpowers:test-driven-development`.
- `pytest` na raiz deve passar 100% ao final, incluindo os testes já existentes (`tests/services/llm/`, `tests/services/storage/`, `tests/test_prompts.py` etc.) — nenhum efeito colateral esperado neles.
- Nenhum teste automatizado chama DynamoDB/AWS real (regra do `CLAUDE.md`) — só `resource`/`table` mockados (`Mock()`), mesmo padrão de `tests/services/llm/test_bedrock_provider.py`.
- `tests/repository/` é pasta nova na `main` (só existe hoje no worktree `feature/nlp-query-totals`) — seguir o mesmo padrão sem `__init__.py`.
- **Conflito de merge esperado:** `feature/nlp-query-totals` também modifica `repository/transaction.py` (adiciona `get_totals_by_period`, já portado aqui em T6). Esta branch (`feat/sqlite-para-dynamodb`) deve ser mesclada primeiro; `feature/nlp-query-totals` faz rebase depois sobre o `repository/` novo.

## Cenários de Teste Manual

1. **SQLite (default, sem AWS):** `DB_BACKEND` não setado (default `sqlite`). Rodar `python main.py`, mandar uma transação de texto → salva normalmente, mensagem de resumo aparece. Reenviar a mesma mensagem → aparece como "não salva, já registrada" (⚠️), sem duplicar no banco.
2. **SUSPEITA (SQLite):** enviar duas mensagens de transação com valor/tipo iguais e descrição levemente diferente, no mesmo dia → a segunda aparece com 🟡 e a nota "parece semelhante", mas **é salva** (soma nos totais).
3. **Café/bolo/café (SQLite):** enviar três transações — café R$8, bolo R$10, café R$8 — a terceira (segundo café) aparece como ⚠️ duplicata, mesmo com o bolo no meio.
4. **DynamoDB real (depois de T1/T2 confirmados):** `DB_BACKEND=dynamo` no `.env`, repetir os cenários 1-3 → mesmo comportamento observável, conferir no console DynamoDB (ou `aws dynamodb scan`) que os Items aparecem com o `sortKey` esperado (`{data}#{fingerprint}`).
5. **Migração:** rodar `python scripts/migrate_sqlite_to_dynamo.py` contra o `guardiao.db` real (ou uma cópia) → contagem de linhas lidas/gravadas bate, `guardiao.db` continua intocado (`git status`/hash do arquivo antes e depois).
6. **Seed de configuração:** rodar `python scripts/seed_config.py <seu_user_id> lazer 300 mensal` → confirmar no DynamoDB que o Item `CONFIG#lazer` foi criado com `teto=300`, `periodo="mensal"`.
7. **Rollback:** voltar `DB_BACKEND=sqlite` (ou remover a env var) com o bot rodando → volta a funcionar sem tocar em Dynamo.

## Fora de Escopo

- Fluxo interativo de confirmação (pergunta e espera resposta) para DUPLICATA_EXATA — versão "sem estado" escolhida nesta fase; fluxo completo fica para decisão futura, não uma task já planejada.
- Qualquer lógica do agente de conselho (Fase 6b): cálculo de "posso gastar X", narrativa sobre orçamento, leitura/escrita de configuração via chat.
- Importador de transações do Notion — decisão do usuário (`INV004`): transações entram pelo fluxo normal de extração via LLM.
- Remoção do `SqliteTransactionRepository`/fallback `DB_BACKEND=sqlite` — permanece até estabilidade confirmada em produção, mesmo ciclo de `GeminiProvider`/`LocalStorageProvider`.
- Webhook, Step Functions, decomposição em Lambda — Fases 4 e 5.
- Rebase/merge de `feature/nlp-query-totals` — branch separada, de outra task; só o conflito esperado fica documentado aqui.
- Ativação do `auth_service` — pré-existente, já anotado como pendência separada no design de `nlp-query-totals`.

## Notas de Execução

- **T1 (tabela DynamoDB) não executado nesta sessão** — ação manual do usuário por `PATTERNS.md` ("criação de recursos AWS é sempre ação manual"). Claude Code nunca roda `aws dynamodb create-table`. Pendente: usuário rodar o comando de T1 e confirmar `TableStatus: ACTIVE`.
- **T2 (edição do JSON) feito; aplicação da policy não** — `scripts/aws/iam-policy-guardiao-dev.json` já tem o `Statement` `DynamoDBReadWriteTransacoesGuardiaoDev` commitado. O comando `aws iam create-policy-version` (que efetivamente aplica a mudança na AWS) é ação manual do usuário, listada em T2.
- **Cenários de Teste Manual 1-3 e 7**: a lógica coberta por eles já está verificada automaticamente e não foi reexecutada via bot real nesta sessão — nenhum ambiente de chat Telegram ao vivo disponível aqui:
  - Cenário 1 (dedup exata + reenvio) ⟷ `tests/repository/test_sqlite_repository.py::test_identical_transaction_inserted_twice_is_duplicata_exata_and_not_duplicated`.
  - Cenário 2 (SUSPEITA insere e sinaliza) ⟷ `tests/repository/test_sqlite_repository.py::test_similar_description_within_window_is_suspeita_and_both_are_kept`.
  - Cenário 3 (café/bolo/café) ⟷ `tests/repository/test_sqlite_repository.py::test_cafe_bolo_cafe_same_day_second_cafe_is_duplicata_exata`.
  - Cenário 7 (rollback pra sqlite) ⟷ `DB_BACKEND` já é `"sqlite"` por default (T3) e `tests/repository/test_factory.py::test_sqlite_repository_selected_when_db_backend_is_sqlite` confirma a seleção.
- **T1 e T2 confirmados na AWS real** (usuário executou fora desta sessão): `aws dynamodb describe-table` retorna `TableStatus: ACTIVE` com `GSI-Categoria`; `aws iam get-policy-version` (`v4`) confirma o `Sid` `DynamoDBReadWriteTransacoesGuardiaoDev`. O comando de T2 tinha um erro (`--profile guardiao-dev` em ação de bootstrap de conta — mesma classe de bug de `TASKS005` T1), corrigido em v1.1.0.
- **Bug real encontrado no Cenário 4 (foto, Dynamo real) e corrigido em v1.2.0**: `PutItem` falhava com `ValidationException` ("AttributeValue for a key attribute cannot contain an empty string value", `IndexName: GSI-Categoria`) sempre que `categoria == ""` (comum quando a extração via LLM não detecta categoria). Corrigido em `DynamoTransactionRepository._save_one` — atributo `categoria` agora é omitido do Item quando vazio, em vez de gravar `""` (padrão de GSI esparsa). TDD aplicado (`tests/repository/test_dynamo_repository.py::test_save_transaction_with_empty_categoria_omits_attribute_from_item`/`test_save_transaction_with_categoria_includes_attribute_in_item`). **Usuário confirmou, após a correção, que o envio de foto real grava com sucesso no DynamoDB.**
- **Bug pré-existente encontrado durante o teste do Cenário 1 (texto)**: `nova-micro` (`TEXT_MODEL_ID`) classifica com pouca confiabilidade se uma frase em português é uma transação — não é causado por TASKS006 (vem de `TASKS004`, Gemini→Bedrock). Investigado e documentado em `docs/analysis/CONTEXT001-nova-micro-classificacao-texto.md` para virar task própria depois; **fora do escopo de TASKS006**, tratado como bloqueio conhecido e aceito para o teste ao vivo dos cenários que dependem de texto.
- **Cenários de Teste Manual 4, 5, 6**: infraestrutura pronta (tabela ativa e policy aplicadas). Cenário 4 confirmado pelo usuário (foto real após a correção do bug de `categoria`). Cenários 5 (migração) e 6 (seed de config) não executados nesta sessão — decisão explícita do usuário de finalizar a task sem rodá-los agora, mesmo padrão de exceção já usado em `TASKS005`.
- **Tentativa de validar Cenários 1-3 via PDF real revelou um problema pré-existente distinto, fora do escopo de TASKS006**: ao reenviar o mesmo PDF de extrato duas vezes, o comportamento de dedup pareceu inconsistente (falsos `duplicata_exata` no primeiro envio, `suspeita` generalizada no reenvio). Investigado com chamadas reais ao Bedrock (duas extrações do mesmo PDF, sem tocar em Dynamo): a causa raiz é que `nova-lite` (`DOCUMENT_MODEL_ID`) **não extrai o documento de forma determinística** — mesma entrada produziu contagens diferentes de transação (24 vs. 26) e descrições com nível de detalhe diferente para a mesma transação real. `repository/dedup.py`/`dynamo_repository.py` seguem corretos e testados — o problema é a instabilidade da extração rio acima, mesma classe do `CONTEXT001` mas afetando o fluxo principal (extrato). Documentado em `docs/analysis/CONTEXT002-nova-lite-extracao-documento-nao-deterministica.md` para virar task própria. **O PDF de teste usado (extrato bancário real do usuário) foi apagado do repositório após o diagnóstico** — não chegou a ser commitado.
- Decisão final registrada pelo usuário: cenários 1-3/7 aceitos como logic-verificados pela suíte automatizada (sem repetição ao vivo — texto bloqueado por `CONTEXT001`, PDF revelou `CONTEXT002` mas confirma que a lógica de dedup em si está correta); cenário 4 confirmado ao vivo com foto; cenários 5-6 pulados por decisão explícita — task fechada com essa cobertura.

## Validação Final

- [x] Tabela DynamoDB criada (T1), `ACTIVE`, com `GSI-Categoria`. Confirmado via `aws dynamodb describe-table`.
- [x] IAM policy ampliada (T2), nova versão (`v4`) aplicada e confirmada via `aws iam get-policy-version` — `Sid` `DynamoDBReadWriteTransacoesGuardiaoDev` presente. Comando corrigido em v1.1.0 (sem `--profile guardiao-dev`).
- [x] `repository/` completo: `provider.py`, `dedup.py`, `sqlite_repository.py`, `dynamo_repository.py`, `config_repository.py`, `factory.py` — com testes passando, sem `repository/transaction.py`.
- [x] `services/transaction_service.py` usa o factory, sem `async_session`/`TransactionRepository(session)` direto.
- [x] `services/message_service.py::format_message` recebe `list[TransactionSaveResult]`.
- [x] Três handlers (`text`, `photo`, `pdf`) propagam o retorno de `save_transactions`.
- [x] `main.py` com `init_db()` condicional a `DB_BACKEND == "sqlite"`.
- [x] `scripts/migrate_sqlite_to_dynamo.py` e `scripts/seed_config.py` existem e rodam sem erro de import.
- [x] `docs/PATTERNS.md` com as cinco novas entradas de broadcast.
- [x] `pytest` 100% verde, incluindo os testes já existentes (96 passed, 0 failed — inclui os 2 testes novos do bug de `categoria` vazia, T7 v1.2.0).
- [x] Cenários de Teste Manual 1-7 — decisão final do usuário: 1-3/7 aceitos como logic-verificados pela suíte automatizada (texto bloqueado por bug pré-existente do `nova-micro`, ver `CONTEXT001-nova-micro-classificacao-texto.md`); 4 confirmado ao vivo pelo usuário (foto real, Dynamo real, após correção do bug de `categoria` vazia); 5 e 6 pulados por decisão explícita do usuário, mesmo padrão de `TASKS005`.
