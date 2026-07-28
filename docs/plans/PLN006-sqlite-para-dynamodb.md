---
type: PLN
version: 1.0.0
author: Victor Veloso
date: 2026-07-27
status: Draft
inv: docs/analysis/INV004-sqlite-para-dynamodb.md
spec: docs/specs/SPEC006-sqlite-para-dynamodb.md
fase: "Fase 3 — docs/analysis/plano-contexto.md"
---

# PLN006 — Dados: SQLite → DynamoDB (+ modelagem de orçamento)

## Contexto

Ver `INV004` (diagnóstico) e `SPEC006` (requisitos). Este documento resolve o "como": estrutura de arquivos, contratos exatos, e a última pendência técnica do INV (comportamento de `init_db()` sob `DB_BACKEND=dynamo`).

**Desvio deliberado do `plano-contexto.md`:** a Fase 3 original dizia "reescrever apenas `repository/`, services e handlers não devem mudar". B3a do SPEC006 (bloquear DUPLICATA_EXATA e pedir confirmação) torna isso impossível de cumprir à risca — decidido com o usuário (rodada de `AskUserQuestion`): "versão simples, sem estado" — `services/transaction_service.py` e os três handlers mudam o mínimo (uma linha cada) para propagar a classificação de dedup na mensagem de resposta, sem nenhum fluxo conversacional novo, sem estado de "pergunta pendente". Ver seção B abaixo.

## Estratégia

### A. Estrutura de arquivos do `repository/`

**Antes** (`repository/transaction.py`, único arquivo, classe concreta acoplada a `AsyncSession`):
```python
class TransactionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session
    async def save_transactions(self, transactions, telegram_user_id): ...
    async def find_by_user(self, telegram_user_id): ...
```

**Depois** — mesmo padrão já usado por `services/llm/` e `services/storage/` (ABC + implementações injetáveis + factory + flag), adaptado para o layer `repository/`:

```
repository/
  provider.py          # ABC TransactionRepository + RepositoryError + TransactionSaveResult
  dedup.py              # funções puras: normalize_description, compute_fingerprint, is_similar
  sqlite_repository.py  # SqliteTransactionRepository (comportamento atual + dedup)
  dynamo_repository.py  # DynamoTransactionRepository (novo)
  config_repository.py  # ConfigRepository (concreta, só Dynamo — ver seção C)
  factory.py             # get_transaction_repository()
```

`repository/transaction.py` é removido (não existe mais "TransactionRepository concreto sem interface" — a condição que bloqueava a abstração deixou de existir, `PATTERNS.md` já previa isso).

`repository/provider.py`:
```python
from abc import ABC, abstractmethod
from datetime import date
from typing import Literal
from pydantic import BaseModel
from models import Transacao

class RepositoryError(Exception):
    """Erro genérico de repository, tratado pelos services (nunca vaza driver nativo)."""

class TransactionSaveResult(BaseModel):
    transacao: Transacao
    status: Literal["nova", "suspeita", "duplicata_exata"]
    similares: list[Transacao] = []

class TransactionRepository(ABC):
    @abstractmethod
    async def save_transactions(self, transactions: list[Transacao], telegram_user_id: int) -> list[TransactionSaveResult]: ...
    @abstractmethod
    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]: ...
    @abstractmethod
    async def get_totals_by_period(self, telegram_user_id: int, start: date, end: date) -> dict[str, float]: ...
```

`TransactionSaveResult` fica em `provider.py` (não em `models.py`) porque é contrato específico do `repository/` (o resultado de uma operação de escrita, não um DTO de domínio como `Transacao` — `Transacao` continua sendo o único tipo que atravessa `services`→`handlers` como dado "puro"; `TransactionSaveResult` é dado + metadado de operação).

`repository/factory.py`:
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
Mesmo formato de `services/llm/factory.py`/`services/storage/factory.py` — decisão já registrada em `PATTERNS.md` ("Troca de provedor externo"), só reaplicada.

**Mudança de lifecycle da sessão SQLite:** hoje `services/transaction_service.py` abre `async with async_session() as session:` e injeta a sessão no construtor. Isso quebra o padrão "uma instância do factory, reutilizável" (LLM/Storage não têm sessão por chamada). `SqliteTransactionRepository` passa a gerenciar sua própria sessão por operação internamente:
```python
class SqliteTransactionRepository(TransactionRepository):
    def __init__(self, session_factory=None):
        self._session_factory = session_factory or async_session

    async def save_transactions(self, transactions, telegram_user_id):
        async with self._session_factory() as session:
            ...
            await session.commit()
```
`session_factory` no construtor segue o mesmo espírito de `client=None` do `BedrockProvider`/`S3StorageProvider` — testável sem monkeypatch (injeta uma session factory de teste).

### B. Dedup — implementação da regra de `SPEC006`

`repository/dedup.py` (puro, sem I/O, compartilhado pelos dois repositories):
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

**`sortKey` de um Item de transação no DynamoDB:** `f"{transacao.data.isoformat()}#{compute_fingerprint(transacao.valor, transacao.tipo, normalize_description(transacao.descricao))}"`.

**Fluxo de `save_transactions` (ambos os backends), por transação da lista (não em lote único — cada uma precisa da própria classificação):**
1. Deriva `sortKey`/fingerprint (B1-B2).
2. Tenta inserir com checagem de unicidade:
   - **Dynamo:** `PutItem` com `ConditionExpression="attribute_not_exists(sortKey)"`. `ConditionalCheckFailedException` → `status="duplicata_exata"`, não insere, segue para a próxima transação da lista.
   - **SQLite:** **sem coluna `fingerprint` nova na entity** (mantém `database/entities/transaction.py` sem mudança, simétrico ao Dynamo — lá o fingerprint também não é um atributo próprio, está embutido no `sortKey`). `SELECT WHERE telegram_user_id=? AND data=?` (só pela data exata, índice já existe), traz os candidatos do dia, recalcula `compute_fingerprint(...)` em memória para cada um via `repository/dedup.py` e compara com o fingerprint da transação nova. Achou igual → `status="duplicata_exata"`, não faz `add()`.
3. Se não é exata: `Query`/`SELECT` por `telegram_user_id` + janela de `SUSPECT_WINDOW_DAYS` (90) dias, filtra candidatos com `valor`/`tipo` iguais e `is_similar(descrição normalizada)`. Achou candidato(s) → `status="suspeita"`, `similares=[...]`, **insere mesmo assim** (SPEC critério 2: SUSPEITA não bloqueia).
4. Nenhuma das duas → `status="nova"`, insere.
5. Ao final: para SQLite, um único `commit()` cobre todos os `add()` da lista (mantém a regra "nunca commit em loop" — só a leitura de checagem roda em loop, a escrita continua em lote). **Para Dynamo isso não é possível da mesma forma — ver "Risco" abaixo.**
6. Retorna `list[TransactionSaveResult]`, mesma ordem da lista de entrada.

**Serviço/handler (mudança mínima, "sem estado"):**
```python
# services/transaction_service.py
async def save_transactions(transactions: list[Transacao], telegram_user_id: int) -> list[TransactionSaveResult]:
    repository = get_transaction_repository()
    return await repository.save_transactions(transactions, telegram_user_id)
```
```python
# services/message_service.py — format_message passa a receber list[TransactionSaveResult]
def format_message(results: list[TransactionSaveResult]) -> str:
    # NOVA/SUSPEITA entram no resumo normalmente (SUSPEITA com uma nota de aviso);
    # DUPLICATA_EXATA vira uma linha "⚠️ não salva (já registrada) — envie de novo com
    # alguma diferença se for uma compra real" e NÃO entra nos totais.
```
```python
# handlers/text_handler.py (e photo_handler.py, pdf_handler.py) — uma linha muda:
results = await save_transactions(transactions, user_id)
msg = format_message(results)   # antes: format_message(transactions)
```
Isso resolve B3a sem nenhum mecanismo de "forçar gravação após confirmação": como a confirmação é "reenviar com uma pequena diferença", a descrição naturalmente muda → `normalize_description` produz outro texto → `compute_fingerprint` produz outro hash → o reenvio já cai em NOVA ou SUSPEITA por conta própria, sem nenhum código especial de override.

### C. Configuração (baldes/dívida) — `ConfigRepository`

`repository/config_repository.py`, **classe concreta, sem ABC** (só uma implementação real — Dynamo; a regra "sem `Protocol`/`ABC` sem segunda implementação real" do `CLAUDE.md` continua valendo aqui, diferente de `TransactionRepository` que já tem duas). Config nunca existiu em SQLite — não há comportamento legado a preservar, e não é gated por `DB_BACKEND` (fala direto com DynamoDB independente do backend de transação ativo, já que a IAM/tabela desta fase cobre os dois).

```python
class ConfigRepository:
    def __init__(self, table_name: str, resource=None):
        self._table = (resource or boto3.resource("dynamodb")).Table(table_name)

    async def save_config(self, telegram_user_id: int, nome: str, teto: float,
                           periodo: Literal["mensal", "unico"], rollover: bool = False,
                           data_limite: date | None = None) -> None: ...
    async def get_config(self, telegram_user_id: int, nome: str) -> ConfigItem | None: ...
    async def list_configs(self, telegram_user_id: int) -> list[ConfigItem]: ...
```
`ConfigItem` (Pydantic, em `repository/provider.py` ao lado de `TransactionSaveResult`): `nome: str`, `teto: float`, `periodo: Literal["mensal","unico"]`, `rollover: bool`, `data_limite: date | None`, `created_at: datetime`, `updated_at: datetime`.

Sem handler/service novo nesta fase (SPEC C4) — população inicial via script administrativo direto (mesma pasta `scripts/`, ex. `scripts/seed_config.py`, chamando `ConfigRepository` diretamente), rodado manualmente pelo usuário.

### D. Migração de dados (SQLite → DynamoDB)

`scripts/migrate_sqlite_to_dynamo.py`: lê todas as linhas de `guardiao.db` via `SqliteTransactionRepository`-like query direta, para cada uma deriva `sortKey`/fingerprint (mesmo `repository/dedup.py`) e grava com `PutItem` condicional individual (nunca `batch_writer` — mesmo motivo da seção "Risco" abaixo: a condição de deduplicação é por item). Ao final, imprime `linhas lidas` vs. `Items gravados` (D2 do SPEC). Não abre `guardiao.db` em modo escrita (D3).

### E. `init_db()` sob `DB_BACKEND=dynamo` (Pergunta em Aberto 4 do INV, resolvida aqui)

**Decisão:** `database/connection.py::init_db()` continua exatamente como está (só faz sentido para SQLite, `Base.metadata.create_all`). A chamada em `main.py` passa a ser condicional:
```python
# main.py
from run_polling.config import DB_BACKEND
if DB_BACKEND == "sqlite":
    asyncio.run(init_db())
```
Nenhuma mudança em `database/connection.py` — mantém a responsabilidade única do módulo (SQLAlchemy/SQLite), sem ele precisar saber que Dynamo existe. Provisionamento da tabela Dynamo continua manual via AWS CLI (`PATTERNS.md`, "Criação de recursos AWS é sempre ação manual").

### F. IAM

`scripts/aws/iam-policy-guardiao-dev.json` ganha um novo `Sid` (nunca substitui os existentes, `PATTERNS.md`):
```json
{
  "Sid": "DynamoDBReadWriteTransacoesGuardiaoDev",
  "Effect": "Allow",
  "Action": ["dynamodb:GetItem", "dynamodb:PutItem", "dynamodb:Query"],
  "Resource": [
    "arn:aws:dynamodb:us-east-2:413948096391:table/GuardiaoFinanceiro-Transacoes-dev",
    "arn:aws:dynamodb:us-east-2:413948096391:table/GuardiaoFinanceiro-Transacoes-dev/index/*"
  ]
}
```
Criação da tabela (`aws dynamodb create-table ...`) é comando manual do TASKS para o usuário rodar com o profile admin (não `guardiao-dev`) — mesmo padrão de `TASKS005` (bootstrap de conta).

## Alternativas Consideradas e Descartadas

1. **Sequência/sufixo no `sortKey` para permitir "forçar gravação" após confirmação** — descartada. Como a UX de confirmação escolhida é "reenvie com uma diferença", o próprio fingerprint já muda no reenvio; nenhum mecanismo de override é necessário. Mais simples, zero código especial.
2. **`ConfigRepository` como ABC com `Protocol`, preparando uma futura segunda implementação** — descartada por `CLAUDE.md` ("nunca ABC sem segunda implementação real"); vira ABC só se/quando aparecer um segundo backend de configuração.
3. **Fluxo interativo completo de confirmação (pergunta e espera resposta)** — descartado nesta fase (decisão do usuário); documentado como possível evolução futura, não uma task já planejada.
4. **`TransactionSaveResult`/config em `models.py`** — descartado; `models.py` fica reservado ao DTO de domínio puro (`Transacao`), que não carrega metadado de operação de escrita.
5. **Persistir saldo do balde/dívida como atributo** — descartado por `SPEC006` C2 (sempre derivado).
6. **`batch_writer` para todas as escritas Dynamo (A5 do SPEC, "quando aplicável")** — parcialmente descartado: não é aplicável a `save_transactions` nem à migração (D1), porque `ConditionExpression` não é suportado pela API `BatchWriteItem` do DynamoDB (só `PutItem`/`DeleteItem` individuais aceitam condição). Só seria aplicável a uma escrita em lote sem checagem de dedup, cenário que não existe nesta fase.

## Arquivos a Modificar/Criar

| Arquivo | Ação |
|---|---|
| `repository/provider.py` | Criar — ABC `TransactionRepository`, `RepositoryError`, `TransactionSaveResult`, `ConfigItem` |
| `repository/dedup.py` | Criar — funções puras de fingerprint/normalização/similaridade |
| `repository/sqlite_repository.py` | Criar — move lógica de `repository/transaction.py` + dedup + `get_totals_by_period` |
| `repository/dynamo_repository.py` | Criar — implementação boto3 |
| `repository/config_repository.py` | Criar — CRUD de configuração, sem ABC |
| `repository/factory.py` | Criar — `get_transaction_repository()` |
| `repository/transaction.py` | Remover (substituído pelos arquivos acima) |
| `services/transaction_service.py` | Modificar — usa factory, propaga `list[TransactionSaveResult]`, expõe `save_config`/`get_config` (repassando para `ConfigRepository`) |
| `services/message_service.py` | Modificar — `format_message` recebe `list[TransactionSaveResult]` |
| `handlers/text_handler.py`, `handlers/photo_handler.py`, `handlers/pdf_handler.py` | Modificar — uma linha cada, passam o retorno de `save_transactions` para `format_message` |
| `database/entities/transaction.py` | Sem mudança |
| `database/connection.py` | Sem mudança |
| `main.py` | Modificar — `init_db()` condicional a `DB_BACKEND == "sqlite"` |
| `run_polling/config.py` | Modificar — adiciona `DB_BACKEND`, `DYNAMO_TABLE_NAME` |
| `scripts/migrate_sqlite_to_dynamo.py` | Criar |
| `scripts/seed_config.py` | Criar (script administrativo simples para popular baldes/dívida) |
| `scripts/aws/iam-policy-guardiao-dev.json` | Modificar — novo `Sid` DynamoDB |
| `docs/PATTERNS.md` | Modificar — broadcast das decisões reutilizáveis (ver abaixo) |
| `tests/repository/test_dedup.py`, `test_sqlite_repository.py`, `test_dynamo_repository.py`, `test_factory.py`, `test_config_repository.py` | Criar |
| `tests/services/test_transaction_service.py`, `test_message_service.py` | Criar/Modificar |

## Riscos

1. **`ConditionExpression` não existe em `BatchWriteItem`.** Cada `PutItem` de transação precisa ser uma chamada individual (não `batch_writer`) quando dedup está ativo — o que é sempre, nesta fase. Custo: mais chamadas de rede que um batch puro, mas correto (dedup exige atomicidade por item). Mitigação: nenhuma necessária, é a única forma correta; só documentar para não ser "otimizado" incorretamente depois.
2. **`boto3` (resource API) exige `Decimal`, não `float`, para atributos numéricos.** `valor`/`teto` precisam de conversão explícita (`Decimal(str(valor))`) antes de `PutItem`, e o inverso na leitura. Esquecer isso é um erro comum e só aparece em runtime real (`TypeError: Float types are not supported`).
3. **Paridade de comportamento entre `sqlite` e `dynamo` para dedup (B7 do SPEC)** exige que os testes rodem a mesma bateria de casos contra os dois backends — meio caminho andado por reaproveitar `repository/dedup.py` (puro, compartilhado), mas a query de candidatos (SQL `BETWEEN` vs. `Query` por `sortKey` range) precisa ser testada separadamente para garantir que a janela de datas seja equivalente.
4. **Custo de `Query` crescente:** a janela de 90 dias busca todos os itens do usuário nesse intervalo a cada inserção — para um usuário com muitas transações/dia isso ainda é barato (volume pessoal, não escala de fintech), mas se algum dia o volume crescer, vale rever. Não é ação agora, só nota para o futuro.
5. **Migração (D1) não é atômica entre SQLite e Dynamo** — se o script falhar no meio, algumas linhas já foram gravadas. Mitigação: script idempotente (reexecutar não duplica, porque o `PutItem` condicional já rejeita o que já foi gravado) — reforça por que a migração também usa a checagem condicional, não `batch_writer`.
6. **`repository/transaction.py` está sendo removido enquanto a branch não mesclada `feature/nlp-query-totals` ainda o modifica** (ela adiciona `get_totals_by_period` a esse mesmo arquivo — motivo pelo qual essa função entrou no escopo desta fase, decisão registrada em `INV004`). Conflito de merge é esperado, não hipotético. Mitigação: esta branch (`feat/sqlite-para-dynamodb`) deve ser mesclada primeiro; `feature/nlp-query-totals` faz rebase depois, sobre o `repository/` novo (`get_totals_by_period` já vai existir na interface `TransactionRepository`, então o rebase deve ser simples — só remove a definição antiga e usa a nova).
7. **`Query` por faixa de data num `sortKey` composto (`{data}#{fingerprint}`) não é um `BETWEEN` trivial.** Um `KeyConditionExpression` de intervalo sobre string (`sortKey BETWEEN :inicio AND :fim`) só funciona de forma confiável se o limite superior for maior que qualquer sufixo possível no dia final — ou seja, usar `:fim = "{data_final}#￿"` (sentinela que ordena depois de qualquer fingerprint hex) em vez de `:fim = "{data_final}"` puro, senão a busca perde itens do último dia da janela cujo fingerprint ordena depois do que seria comparado. Mesmo golpe de atenção vale para `get_totals_by_period` (E2), que usa o mesmo padrão de acesso.

## Broadcast para `docs/PATTERNS.md`

Estas decisões são reutilizáveis por tasks futuras (Fase 6b principalmente) — serão adicionadas à seção "Decisões Estabelecidas" do `PATTERNS.md` junto com o TASKS006:

1. Fingerprint de dedup (`data + hash(valor+tipo+descrição normalizada)` como `sortKey`) — qualquer código futuro que escreva transações (ex. um eventual importador) deve passar por `repository/dedup.py`, nunca reinventar a checagem.
2. `ConfigRepository` sem ABC, mesmo padrão de "repository concreto até haver 2ª implementação real".
3. `BatchWriteItem`/`ConditionExpression` incompatíveis — qualquer escrita em lote no DynamoDB que precise de dedup usa `PutItem` individual condicional, nunca `batch_writer`.
4. Baldes e dívida no mesmo shape de Item (`periodo` distingue), saldo sempre derivado — Fase 6b não deve reabrir essa decisão.
