---
type: TASKS
version: 1.0.0
author: Victor Veloso
date: 2026-07-28
status: Done
inv: docs/analysis/INV008-confirmacao-duplicata-exata.md
spec: docs/specs/SPEC010-confirmacao-duplicata-exata.md
plan: docs/plans/PLN010-confirmacao-duplicata-exata.md
---

# TASKS010 — Confirmação com estado para `DUPLICATA_EXATA` e `SUSPEITA`

## Decisões vinculantes (de `SPEC010`/`PLN010`, não redecidir aqui)

- Escopo **só Dynamo** — `SqliteTransactionRepository` e o ABC `TransactionRepository` não ganham os métodos novos como abstratos.
- Pendência = novo Item na mesma tabela (`sortKey = "PENDENTE#{uuid4().hex}"`), nunca em `context.user_data`. Nunca expira sozinha (só sai do estado "pendente" por ação explícita do usuário).
- Idempotência de entrega = novo Item (`sortKey = "PROCESSADO#{update_id}"`) com TTL nativo do DynamoDB (24h) — janela recente, não retenção permanente.
- Botões inline (`InlineKeyboardButton`/`CallbackQueryHandler`), nunca texto livre, para resolver uma pendência — tanto na resposta imediata (R12) quanto no comando `/pendencias` (R13).
- Confirmar ("Sim") grava com `sortKey = "{data}#{fingerprint}#{pendencia_id}"` (sufixo único, sem `ConditionExpression` — a decisão já foi validada pelo usuário).
- Nenhuma dependência nova (sem `APScheduler`/`JobQueue` — fora de escopo).
- **Refinamento sobre o `PLN010`**: o campo que o `TransactionSaveResult` ganha é `pendencia: PendingConfirmation | None = None` (objeto completo), não só `pendencia_id: str | None`. Motivo: o handler precisa do texto/motivo/similares/timestamps para montar a mensagem com botões (R12) sem uma segunda consulta ao DynamoDB — o dado já está em memória no momento em que a pendência é criada.
- **Refinamento sobre o `PLN010`**: `PendingConfirmation` ganha um campo a mais não detalhado no PLN — `similar_criado_em: datetime | None = None` — o timestamp de chegada da transação similar/colidente encontrada, necessário para o cálculo do intervalo do R17 (calibração por janela de tempo). Sem esse campo não há como comparar os dois timestamps, já que `Transacao` (DTO) nunca ganha um campo de horário (Non-Goal do `SPEC010`).
- Limiar concreto para "intervalo curto" do R17 (não especificado no SPEC/PLN, decidido aqui): **5 minutos**. Abaixo disso, texto sugere duplo-envio; acima, texto neutro.

- [x] T1
- [ ] T2
- [x] T3
- [x] T4
- [x] T5
- [x] T6
- [x] T7
- [x] T8
- [x] T9
- [x] T10

## T1 — IAM: adicionar `dynamodb:DeleteItem` (ação manual do usuário)

**Motivo:** `resolve_pending` (T4) precisa apagar o Item de pendência (`Não`, e `Sim` depois de gravar a transação) — a policy atual (`scripts/aws/iam-policy-guardiao-dev.json`) só tem `GetItem`/`PutItem`/`Query`, nunca precisou de `DeleteItem` até agora.

**Arquivo:** `scripts/aws/iam-policy-guardiao-dev.json` — Claude Code edita (é código no repo); o usuário roda os comandos AWS CLI depois.

**Depois** (adicionar `"dynamodb:DeleteItem"` ao array `Action` do statement `DynamoDBReadWriteTransacoesGuardiaoDev`, sem tocar no resto do arquivo):
```json
    {
      "Sid": "DynamoDBReadWriteTransacoesGuardiaoDev",
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:Query",
        "dynamodb:DeleteItem"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-2:413948096391:table/GuardiaoFinanceiro-Transacoes-dev",
        "arn:aws:dynamodb:us-east-2:413948096391:table/GuardiaoFinanceiro-Transacoes-dev/index/*"
      ]
    }
```

Comando para o usuário rodar após o commit (mesma mecânica de `TASKS006` T2 — profile **default**, nunca `--profile guardiao-dev`, por ser ação de bootstrap de conta):
```bash
aws iam create-policy-version \
  --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock \
  --policy-document file://scripts/aws/iam-policy-guardiao-dev.json \
  --set-as-default
```

**Critério de aceitação:** `aws iam get-policy-version --policy-arn arn:aws:iam::413948096391:policy/guardiao-financeiro-dev-bedrock --version-id <nova-versao> --profile guardiao-dev` mostra `dynamodb:DeleteItem` no `Sid` `DynamoDBReadWriteTransacoesGuardiaoDev`.

## T2 — Habilitar TTL na tabela DynamoDB (ação manual do usuário)

**Motivo:** o Item `PROCESSADO#{update_id}` (idempotência, T4) só expira sozinho se o atributo `expiraEm` estiver configurado como TTL da tabela.

```bash
aws dynamodb update-time-to-live \
  --table-name GuardiaoFinanceiro-Transacoes-dev \
  --time-to-live-specification "Enabled=true,AttributeName=expiraEm" \
  --region us-east-2
```

**Critério de aceitação:** `aws dynamodb describe-time-to-live --table-name GuardiaoFinanceiro-Transacoes-dev --region us-east-2` retorna `"TimeToLiveStatus": "ENABLED"` (ou `"ENABLING"` logo após rodar o comando) com `"AttributeName": "expiraEm"`.

> Nota: a expiração de TTL do DynamoDB não é instantânea (pode levar até algumas horas além do previsto) — aceitável aqui, porque o objetivo é só cobrir reentrega de curto prazo (R2 do SPEC010), não uma garantia de limpeza exata.

## T3 — `repository/provider.py`

**Antes** (trechos relevantes):
```python
class TransactionSaveResult(BaseModel):
    transacao: Transacao
    status: Literal["nova", "suspeita", "duplicata_exata"]
    similares: list[Transacao] = []
```

**Depois:**
```python
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from models import Transacao


class RepositoryError(Exception):
    """Erro genérico de repository, tratado pelos services (nunca vaza driver nativo)."""


class PendingConfirmation(BaseModel):
    id: str
    transacao: Transacao
    motivo: Literal["duplicata_exata", "suspeita"]
    similares: list[Transacao] = []
    criado_em: datetime
    similar_criado_em: datetime | None = None


class TransactionSaveResult(BaseModel):
    transacao: Transacao
    status: Literal["nova", "suspeita", "duplicata_exata"]
    similares: list[Transacao] = []
    pendencia: PendingConfirmation | None = None
```

O resto do arquivo (`ConfigItem`, `TransactionRepository` ABC) não muda — os métodos novos (`find_pending_by_user`, `resolve_pending`, `try_claim_update`) **não** entram no ABC (decisão vinculante, escopo só Dynamo).

**Teste** (`tests/repository/test_provider.py`, adicionar):
```python
def test_pending_confirmation_accepts_expected_fields():
    now = datetime(2026, 1, 1, 12, 0, 0)
    pendencia = PendingConfirmation(
        id="abc123", transacao=_transacao(), motivo="suspeita", criado_em=now,
    )
    assert pendencia.similares == []
    assert pendencia.similar_criado_em is None


def test_pending_confirmation_rejects_motivo_outside_literal():
    now = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValidationError):
        PendingConfirmation(id="abc123", transacao=_transacao(), motivo="invalido", criado_em=now)


def test_transaction_save_result_accepts_pendencia_field():
    now = datetime(2026, 1, 1, 12, 0, 0)
    pendencia = PendingConfirmation(id="abc123", transacao=_transacao(), motivo="suspeita", criado_em=now)
    result = TransactionSaveResult(transacao=_transacao(), status="suspeita", pendencia=pendencia)
    assert result.pendencia.id == "abc123"


def test_transaction_save_result_pendencia_defaults_to_none():
    result = TransactionSaveResult(transacao=_transacao(), status="nova")
    assert result.pendencia is None
```
(importar `PendingConfirmation` no topo do arquivo de teste, junto de `ConfigItem`/`TransactionRepository`/`TransactionSaveResult` já importados)

**Critério de aceitação:** os 4 testes novos passam; os testes já existentes de `TransactionSaveResult`/`ConfigItem`/`TransactionRepository` continuam passando sem alteração.

## T4 — `repository/dynamo_repository.py` (reescrita completa)

**Arquivo inteiro, depois:**
```python
import time
from datetime import date, datetime, time as dt_time, timedelta, timezone
from decimal import Decimal
from uuid import uuid4

import boto3
from boto3.dynamodb.conditions import Attr, Key
from botocore.exceptions import ClientError

from models import Transacao
from repository.dedup import (
    SUSPECT_WINDOW_DAYS,
    compute_fingerprint,
    is_similar,
    normalize_description,
)
from repository.provider import (
    PendingConfirmation,
    RepositoryError,
    TransactionRepository,
    TransactionSaveResult,
)

_HIGH_SENTINEL = "￿"
_PROCESSADO_TTL_SECONDS = 24 * 60 * 60
_ESPECIAIS = ("CONFIG#", "PENDENTE#", "PROCESSADO#")


def _item_to_transacao(item: dict) -> Transacao:
    return Transacao(
        data=date.fromisoformat(item["data"]),
        descricao=item["descricao"],
        valor=float(item["valor"]),
        tipo=item["tipo"],
        categoria=item.get("categoria", ""),
    )


def _transacao_to_map(t: Transacao) -> dict:
    return {
        "data": t.data.isoformat(),
        "descricao": t.descricao,
        "valor": Decimal(str(t.valor)),
        "tipo": t.tipo,
        "categoria": t.categoria,
    }


def _criado_em_or_fallback(item: dict) -> datetime:
    raw = item.get("criadoEm")
    if raw:
        return datetime.fromisoformat(raw)
    return datetime.combine(date.fromisoformat(item["data"]), dt_time.min, tzinfo=timezone.utc)


def _item_to_pending(item: dict) -> PendingConfirmation:
    similar_raw = item.get("similarCriadoEm")
    return PendingConfirmation(
        id=item["sortKey"].removeprefix("PENDENTE#"),
        transacao=_item_to_transacao(item["transacao"]),
        motivo=item["motivo"],
        similares=[_item_to_transacao(s) for s in item.get("similares", [])],
        criado_em=datetime.fromisoformat(item["criadoEm"]),
        similar_criado_em=datetime.fromisoformat(similar_raw) if similar_raw else None,
    )


class DynamoTransactionRepository(TransactionRepository):
    def __init__(self, table_name: str, resource=None):
        self._table = (resource or boto3.resource("dynamodb", region_name="us-east-2")).Table(table_name)

    async def save_transactions(
        self, transactions: list[Transacao], telegram_user_id: int
    ) -> list[TransactionSaveResult]:
        criado_em = datetime.now(timezone.utc)
        return [await self._save_one(t, telegram_user_id, criado_em) for t in transactions]

    async def _save_one(
        self, t: Transacao, telegram_user_id: int, criado_em: datetime
    ) -> TransactionSaveResult:
        descricao_norm = normalize_description(t.descricao)
        fingerprint = compute_fingerprint(t.valor, t.tipo, descricao_norm)
        sort_key = f"{t.data.isoformat()}#{fingerprint}"
        user_id = str(telegram_user_id)

        exato = await self._find_exact(user_id, sort_key)
        if exato is not None:
            pendencia = await self._create_pending(user_id, t, "duplicata_exata", [exato], criado_em)
            return TransactionSaveResult(transacao=t, status="duplicata_exata", pendencia=pendencia)

        similares = await self._find_similar(user_id, t, descricao_norm, exclude_sort_key=sort_key)
        if similares:
            pendencia = await self._create_pending(user_id, t, "suspeita", similares, criado_em)
            return TransactionSaveResult(
                transacao=t, status="suspeita", similares=[s for s, _ in similares], pendencia=pendencia
            )

        item = {
            "userId": user_id,
            "sortKey": sort_key,
            "criadoEm": criado_em.isoformat(),
            **_transacao_to_map(t),
        }
        try:
            self._table.put_item(Item=item)
        except ClientError as exc:
            raise RepositoryError(f"falha ao gravar transação no DynamoDB: {exc}") from exc
        return TransactionSaveResult(transacao=t, status="nova")

    async def _find_exact(self, user_id: str, sort_key: str) -> tuple[Transacao, datetime] | None:
        try:
            response = self._table.get_item(Key={"userId": user_id, "sortKey": sort_key})
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar duplicata exata: {exc}") from exc
        item = response.get("Item")
        if not item:
            return None
        return _item_to_transacao(item), _criado_em_or_fallback(item)

    async def _find_similar(
        self, user_id: str, t: Transacao, descricao_norm: str, exclude_sort_key: str
    ) -> list[tuple[Transacao, datetime]]:
        start = (t.data - timedelta(days=SUSPECT_WINDOW_DAYS)).isoformat()
        end = (t.data + timedelta(days=SUSPECT_WINDOW_DAYS)).isoformat()
        try:
            response = self._table.query(
                KeyConditionExpression=(
                    Key("userId").eq(user_id) & Key("sortKey").between(f"{start}#", f"{end}#{_HIGH_SENTINEL}")
                )
            )
            pendentes_response = self._table.query(
                KeyConditionExpression=Key("userId").eq(user_id) & Key("sortKey").begins_with("PENDENTE#"),
                FilterExpression=Attr("transacao.data").between(start, end),
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar candidatos de SUSPEITA: {exc}") from exc

        candidatos: list[tuple[str, Transacao, datetime]] = []
        for item in response.get("Items", []):
            if item["sortKey"] == exclude_sort_key:
                # o item recém-gravado por esta própria chamada já está visível na
                # Query (put_item já commitou antes de chegarmos aqui) — sem essa
                # exclusão, toda transação "nova" se compararia contra si mesma
                # (similaridade 1.0) e seria classificada como "suspeita".
                continue
            if float(item["valor"]) != t.valor or item["tipo"] != t.tipo:
                continue
            candidatos.append((item["descricao"], _item_to_transacao(item), _criado_em_or_fallback(item)))

        for pend_item in pendentes_response.get("Items", []):
            candidata = pend_item["transacao"]
            if float(candidata["valor"]) != t.valor or candidata["tipo"] != t.tipo:
                continue
            candidatos.append((
                candidata["descricao"],
                _item_to_transacao(candidata),
                datetime.fromisoformat(pend_item["criadoEm"]),
            ))

        return [
            (transacao, criado_em)
            for descricao, transacao, criado_em in candidatos
            if is_similar(normalize_description(descricao), descricao_norm)
        ]

    async def _create_pending(
        self,
        user_id: str,
        t: Transacao,
        motivo: str,
        similares: list[tuple[Transacao, datetime]],
        criado_em: datetime,
    ) -> PendingConfirmation:
        pendencia_id = uuid4().hex
        item = {
            "userId": user_id,
            "sortKey": f"PENDENTE#{pendencia_id}",
            "motivo": motivo,
            "transacao": _transacao_to_map(t),
            "similares": [_transacao_to_map(s) for s, _ in similares],
            "criadoEm": criado_em.isoformat(),
        }
        if similares:
            item["similarCriadoEm"] = similares[0][1].isoformat()
        try:
            self._table.put_item(Item=item)
        except ClientError as exc:
            raise RepositoryError(f"falha ao gravar pendência: {exc}") from exc
        return PendingConfirmation(
            id=pendencia_id,
            transacao=t,
            motivo=motivo,
            similares=[s for s, _ in similares],
            criado_em=criado_em,
            similar_criado_em=similares[0][1] if similares else None,
        )

    async def find_pending_by_user(self, telegram_user_id: int) -> list[PendingConfirmation]:
        user_id = str(telegram_user_id)
        try:
            response = self._table.query(
                KeyConditionExpression=Key("userId").eq(user_id) & Key("sortKey").begins_with("PENDENTE#")
            )
        except ClientError as exc:
            raise RepositoryError(f"falha ao listar pendências: {exc}") from exc
        return [_item_to_pending(item) for item in response.get("Items", [])]

    async def resolve_pending(self, telegram_user_id: int, pendencia_id: str, decisao: str) -> str:
        user_id = str(telegram_user_id)
        sort_key = f"PENDENTE#{pendencia_id}"
        try:
            response = self._table.get_item(Key={"userId": user_id, "sortKey": sort_key})
        except ClientError as exc:
            raise RepositoryError(f"falha ao ler pendência: {exc}") from exc
        item = response.get("Item")
        if not item:
            return "ja_resolvida"

        try:
            self._table.delete_item(
                Key={"userId": user_id, "sortKey": sort_key},
                ConditionExpression="attribute_exists(sortKey)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return "ja_resolvida"
            raise RepositoryError(f"falha ao remover pendência: {exc}") from exc

        if decisao == "nao":
            return "descartada"

        pendencia = _item_to_pending(item)
        t = pendencia.transacao
        fingerprint = compute_fingerprint(t.valor, t.tipo, normalize_description(t.descricao))
        final_sort_key = f"{t.data.isoformat()}#{fingerprint}#{pendencia_id}"
        final_item = {
            "userId": user_id,
            "sortKey": final_sort_key,
            "criadoEm": pendencia.criado_em.isoformat(),
            **_transacao_to_map(t),
        }
        try:
            self._table.put_item(Item=final_item)
        except ClientError as exc:
            raise RepositoryError(f"falha ao gravar transação confirmada: {exc}") from exc
        return "confirmada"

    async def try_claim_update(self, telegram_user_id: int, update_id: int) -> bool:
        user_id = str(telegram_user_id)
        expira_em = int(time.time()) + _PROCESSADO_TTL_SECONDS
        try:
            self._table.put_item(
                Item={"userId": user_id, "sortKey": f"PROCESSADO#{update_id}", "expiraEm": expira_em},
                ConditionExpression="attribute_not_exists(sortKey)",
            )
            return True
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return False
            raise RepositoryError(f"falha ao registrar idempotência de update: {exc}") from exc

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        try:
            response = self._table.query(KeyConditionExpression=Key("userId").eq(str(telegram_user_id)))
        except ClientError as exc:
            raise RepositoryError(f"falha ao consultar transações do usuário: {exc}") from exc
        return [
            _item_to_transacao(item)
            for item in response.get("Items", [])
            if not item["sortKey"].startswith(_ESPECIAIS)
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
            if item["sortKey"].startswith(_ESPECIAIS):
                continue
            key = key_map.get(item.get("tipo"))
            if key:
                totals[key] += float(item["valor"])
        return totals
```

**Notas de implementação importantes:**
- `_save_one` deixou de fazer `put_item` condicional como primeiro passo — agora faz **leitura antes de escrever** (`_find_exact`/`_find_similar` primeiro, `put_item` sem condição só se nada colidir). Isso abre uma janela de corrida teórica (duas mensagens idênticas processadas em paralelo poderiam ambas passar pela checagem e uma sobrescrever a outra) — aceito como risco menor dado o volume pessoal do projeto e o processamento tipicamente sequencial do `python-telegram-bot` por usuário; documentar em "Riscos" abaixo, não resolver aqui.
- `_find_similar` roda **duas** Queries agora (transações confirmadas + `PENDENTE#`) — implementa R6 do SPEC (fecha o furo de duplicata que não seria pega por não comparar contra pendências abertas).
- Um "Sim" confirmado grava com `sortKey` sufixado pelo `pendencia_id` — um duplicado exato *futuro* desse mesmo item não é mais pego por `_find_exact` (R3), mas **sempre** é pego por `_find_similar` (R4), porque a descrição normalizada bate 100% (`is_similar` = 1.0). Vira `suspeita` em vez de `duplicata_exata` nesse caso específico — mudança de rótulo, não de comportamento (documentado para não ser redescoberto como bug).
- `find_by_user`/`get_totals_by_period` agora excluem três prefixos (`CONFIG#`, `PENDENTE#`, `PROCESSADO#`), não só `CONFIG#`.

**Teste** (`tests/repository/test_dynamo_repository.py` — reescrever os 4 testes afetados, adicionar os novos; `resource = Mock()`/`resource.Table.return_value = table`, sem chamada real à AWS):

Testes a **reescrever** (comportamento mudou de "bloqueia"/"grava com nota" para "cria pendência"):
- `test_put_item_condition_failure_is_duplicata_exata_and_skips_query` → renomear/reescrever para `test_exact_match_creates_pending_confirmation_instead_of_blocking`: mock `table.get_item` retornando um Item existente com o mesmo `sortKey` calculado; `table.query` (janela de `SUSPEITA`) **e** `table.query` (janela de `PENDENTE#`) não precisam ser chamados nesse caminho (retorna antes, no `_find_exact`); resultado esperado: `status="duplicata_exata"`, `result.pendencia is not None`, `result.pendencia.motivo == "duplicata_exata"`; `table.put_item` chamado **uma vez** (para gravar o Item de pendência `PENDENTE#...`), nunca para a transação em si.
- `test_cafe_bolo_cafe_same_day_second_cafe_is_duplicata_exata` → mantém o cenário (café, bolo, café) mas o segundo café agora vira pendência, não bloqueio silencioso: `table.get_item` no terceiro `save_transactions` retorna o Item do primeiro café; resultado esperado do terceiro: `status="duplicata_exata"` com `pendencia` preenchida.
- `test_save_transaction_with_similar_candidate_is_suspeita` → mock `table.get_item` retornando `{}` (sem `"Item"`, ou seja, sem duplicata exata), `table.query` (janela real) retornando o candidato similar, `table.query` (janela `PENDENTE#`) retornando `{"Items": []}`; resultado esperado: `status="suspeita"`, `pendencia.motivo == "suspeita"`, `pendencia.similares` com 1 item; **`table.put_item` não deve ser chamado para a transação em si**, só para o Item de pendência.
- `test_save_new_transaction_excludes_itself_from_suspeita_check` → mesmo ajuste de mocks (`get_item` retorna `{}`, duas chamadas de `query`); resultado esperado continua `status="nova"`, mas agora `table.put_item` é chamado **uma vez** para a transação (sem `ConditionExpression`, diferente do teste antigo que verificava a presença da condição).

Testes **novos**:
- `test_find_similar_includes_pending_items_from_same_user` — `table.query` da janela real retorna vazio; `table.query` de `PENDENTE#` retorna um Item de pendência cujo `transacao` embutido tem mesmo `valor`/`tipo` e descrição similar → resultado: nova transação também vira `suspeita` (fecha o furo do R6).
- `test_resolve_pending_sim_writes_transaction_with_suffixed_sort_key_and_deletes_pending` — `table.get_item` retorna o Item de pendência; após `resolve_pending(..., decisao="sim")`, `table.delete_item` foi chamado com `ConditionExpression="attribute_exists(sortKey)"`, e `table.put_item` foi chamado com um `sortKey` terminando em `#<pendencia_id>` e sem `ConditionExpression`.
- `test_resolve_pending_nao_deletes_without_writing_transaction` — mesmo setup, `decisao="nao"`: `table.delete_item` chamado, `table.put_item` **não** chamado.
- `test_resolve_pending_already_resolved_returns_ja_resolvida_without_deleting_or_writing` — `table.get_item` retorna `{}` (sem `"Item"`) → retorno `"ja_resolvida"`, nem `delete_item` nem `put_item` chamados.
- `test_resolve_pending_double_tap_race_returns_ja_resolvida` — `table.get_item` retorna um Item válido, mas `table.delete_item` levanta `ClientError` com `Code="ConditionalCheckFailedException"` (simula segundo toque já ter apagado) → retorno `"ja_resolvida"`, `put_item` **não** chamado mesmo com `decisao="sim"`.
- `test_find_pending_by_user_queries_with_begins_with_pendente` — `table.query` retorna uma lista de Items `PENDENTE#...`; resultado é uma lista de `PendingConfirmation` com `id` extraído corretamente do `sortKey` (sem o prefixo).
- `test_try_claim_update_first_time_returns_true` — `table.put_item` sem erro → `True`.
- `test_try_claim_update_already_processed_returns_false` — `table.put_item` levanta `ConditionalCheckFailedException` → `False`, sem propagar exceção.
- `test_find_by_user_excludes_pending_and_processado_items` — `table.query` retorna uma mistura de Item de transação real, `CONFIG#`, `PENDENTE#` e `PROCESSADO#` → só a transação real aparece no resultado.

**Critério de aceitação:** todos os testes (reescritos + novos) passam com `resource`/`table` mockados — nenhuma chamada real a AWS.

## T5 — `services/transaction_service.py`

**Depois** (adicionar ao arquivo existente, sem alterar `save_transactions`/`get_transactions`/`get_totals`):
```python
async def get_pending(telegram_user_id: int) -> list[PendingConfirmation]:
    repository = get_transaction_repository()
    return await repository.find_pending_by_user(telegram_user_id)


async def resolve_pending(telegram_user_id: int, pendencia_id: str, decisao: str) -> str:
    repository = get_transaction_repository()
    return await repository.resolve_pending(telegram_user_id, pendencia_id, decisao)


async def claim_update(telegram_user_id: int, update_id: int) -> bool:
    repository = get_transaction_repository()
    return await repository.try_claim_update(telegram_user_id, update_id)
```
(importar `PendingConfirmation` de `repository.provider` no topo do arquivo)

**Teste** (`tests/services/test_transaction_service.py`, mesmo padrão `AsyncMock` + `monkeypatch` já usado no arquivo):
```python
async def test_get_pending_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.find_pending_by_user.return_value = ["pendencia-fake"]
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    result = await transaction_service.get_pending(42)

    repository.find_pending_by_user.assert_awaited_once_with(42)
    assert result == ["pendencia-fake"]


async def test_resolve_pending_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.resolve_pending.return_value = "confirmada"
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    result = await transaction_service.resolve_pending(42, "abc123", "sim")

    repository.resolve_pending.assert_awaited_once_with(42, "abc123", "sim")
    assert result == "confirmada"


async def test_claim_update_delegates_to_repository_and_returns_result(monkeypatch):
    repository = AsyncMock()
    repository.try_claim_update.return_value = True
    monkeypatch.setattr(transaction_service, "get_transaction_repository", lambda: repository)

    result = await transaction_service.claim_update(42, 999)

    repository.try_claim_update.assert_awaited_once_with(42, 999)
    assert result is True
```

**Critério de aceitação:** os 3 testes novos passam; testes existentes do arquivo continuam passando sem alteração.

## T6 — `services/message_service.py`

**Antes** (`format_message`, trecho relevante):
```python
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
        notes = []
        if r.status == "suspeita":
            notes.append("parece semelhante a uma já registrada")
```

**Depois** (`format_message` reescrito — itens `suspeita`/`duplicata_exata` não contam mais nos totais, porque não são mais gravados de imediato; texto muda para refletir que viraram pendência, não bloqueio nem gravação com nota):
```python
    for r in results:
        t = r.transacao
        if r.status in ("suspeita", "duplicata_exata"):
            lines.append(
                f"🟡 {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f} "
                "(aguardando sua confirmação, veja a mensagem abaixo)"
            )
            continue

        emoji = "🟢" if t.tipo == "entrada" else "🔴"
        if t.tipo == "entrada":
            income_total += t.valor
        else:
            expense_total += t.valor
        notes = []
```
(o resto do corpo do loop — notas de categoria/valor, resumo final — não muda)

**Nova função**, adicionar ao final do arquivo (formatação de pendência, calibrada pelo intervalo de tempo — R15/R17 do SPEC):
```python
from datetime import timedelta

from repository.provider import PendingConfirmation

_JANELA_CURTA = timedelta(minutes=5)


def format_pending_message(pendencia: PendingConfirmation) -> str:
    t = pendencia.transacao
    motivo_label = "um lançamento idêntico" if pendencia.motivo == "duplicata_exata" else "um lançamento parecido"
    linhas = [
        f"🟡 Encontrei {motivo_label} ao tentar registrar:",
        f"{t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}",
    ]
    if pendencia.similar_criado_em is not None:
        intervalo = abs(pendencia.criado_em - pendencia.similar_criado_em)
        if intervalo <= _JANELA_CURTA:
            linhas.append("Foi enviado bem perto de um lançamento parecido — pode ter sido sem querer.")
        else:
            linhas.append("Já existe um lançamento parecido registrado antes.")
    linhas.append("Confirma que quer registrar mesmo assim?")
    return "\n".join(linhas)
```

**Teste** (`tests/services/test_message_service.py`):

Reescrever (comportamento mudou):
- `test_format_message_duplicata_exata_shows_warning_and_excludes_from_totals` → texto esperado passa a ser `"aguardando sua confirmação"` (não mais `"não salva, já registrada"`); `"⚠️"` deixa de aparecer, `"🟡"` aparece; totais continuam excluindo esse item.
- `test_format_message_suspeita_shows_marker_and_includes_in_totals` → renomear para refletir que **não inclui mais nos totais**: `"Saídas: R$ 0.00"` (não mais `8.00`); texto passa a ser `"aguardando sua confirmação"` (não mais `"parece semelhante"`).
- `test_format_message_suspeita_e_categoria_outros_combina_as_duas_notas` → como o item `suspeita` agora só gera a linha de pendência (sem chegar a montar a nota de categoria, que só roda para itens que não são `suspeita`/`duplicata_exata`), o teste deixa de fazer sentido como estava — reescrever para confirmar que a nota de categoria **não aparece** junto da linha de pendência (a categoria só é avaliada/exibida quando a transação é de fato gravada).

Novos:
```python
def test_format_pending_message_duplicata_exata_label():
    now = datetime(2026, 6, 15, 12, 0, 0)
    pendencia = PendingConfirmation(
        id="abc", transacao=_transacao(), motivo="duplicata_exata", criado_em=now,
    )
    texto = format_pending_message(pendencia)
    assert "lançamento idêntico" in texto
    assert "Confirma que quer registrar mesmo assim?" in texto


def test_format_pending_message_short_interval_suggests_double_send():
    criado_em = datetime(2026, 6, 15, 12, 5, 0)
    similar_criado_em = datetime(2026, 6, 15, 12, 0, 0)  # 5 min de diferença
    pendencia = PendingConfirmation(
        id="abc", transacao=_transacao(), motivo="suspeita",
        criado_em=criado_em, similar_criado_em=similar_criado_em,
    )
    texto = format_pending_message(pendencia)
    assert "pode ter sido sem querer" in texto


def test_format_pending_message_long_interval_uses_neutral_text():
    criado_em = datetime(2026, 6, 15, 18, 0, 0)
    similar_criado_em = datetime(2026, 6, 15, 12, 0, 0)  # 6 horas de diferença
    pendencia = PendingConfirmation(
        id="abc", transacao=_transacao(), motivo="suspeita",
        criado_em=criado_em, similar_criado_em=similar_criado_em,
    )
    texto = format_pending_message(pendencia)
    assert "Já existe um lançamento parecido registrado antes." in texto
    assert "pode ter sido sem querer" not in texto
```
(importar `datetime`, `PendingConfirmation`, `format_pending_message` no topo do arquivo de teste)

**Critério de aceitação:** todos os testes (reescritos + novos) passam.

## T7 — `handlers/pending_handler.py` (arquivo novo)

```python
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes

from services.message_service import format_pending_message
from services.transaction_service import get_pending, resolve_pending


def build_confirmation_keyboard(pendencia_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Sim", callback_data=f"pend:sim:{pendencia_id}"),
        InlineKeyboardButton("🚫 Não", callback_data=f"pend:nao:{pendencia_id}"),
    ]])


async def get_pendencias(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    pendencias = await get_pending(user_id)

    if not pendencias:
        await update.message.reply_text("Nenhuma pendência em aberto. 🎉")
        return

    for pendencia in pendencias:
        texto = format_pending_message(pendencia)
        await update.message.reply_text(texto, reply_markup=build_confirmation_keyboard(pendencia.id))


async def handle_pending_callback(update: Update, context: ContextTypes):
    query = update.callback_query
    await query.answer()

    _, decisao, pendencia_id = query.data.split(":", 2)
    user_id = update.effective_user.id

    resultado = await resolve_pending(user_id, pendencia_id, decisao)

    textos = {
        "confirmada": "✅ Confirmado e salvo.",
        "descartada": "🚫 Descartado — não foi salvo.",
        "ja_resolvida": "Essa pendência já tinha sido resolvida antes.",
    }
    await query.edit_message_text(textos[resultado])
```

**Teste** (`tests/handlers/test_pending_handler.py`, arquivo novo — mesmo padrão `Mock`/`AsyncMock` de `tests/handlers/test_text_handler.py`):
```python
from unittest.mock import AsyncMock, Mock

import handlers.pending_handler as pending_handler


def _build_update():
    update = Mock()
    update.effective_user.id = 42
    update.message.reply_text = AsyncMock()
    return update


async def test_get_pendencias_no_pending_replies_with_empty_message(monkeypatch):
    update = _build_update()
    context = Mock()
    monkeypatch.setattr(pending_handler, "get_pending", AsyncMock(return_value=[]))

    await pending_handler.get_pendencias(update, context)

    update.message.reply_text.assert_awaited_once()
    assert "Nenhuma pendência" in update.message.reply_text.call_args.args[0]


async def test_get_pendencias_sends_one_message_per_pending_with_keyboard(monkeypatch):
    update = _build_update()
    context = Mock()
    pendencia_fake = Mock(id="abc123")
    monkeypatch.setattr(pending_handler, "get_pending", AsyncMock(return_value=[pendencia_fake]))
    monkeypatch.setattr(pending_handler, "format_pending_message", Mock(return_value="texto da pendência"))

    await pending_handler.get_pendencias(update, context)

    update.message.reply_text.assert_awaited_once()
    call = update.message.reply_text.call_args
    assert call.args[0] == "texto da pendência"
    assert "reply_markup" in call.kwargs


async def _build_callback_update(callback_data: str):
    update = Mock()
    update.effective_user.id = 42
    update.callback_query.data = callback_data
    update.callback_query.answer = AsyncMock()
    update.callback_query.edit_message_text = AsyncMock()
    return update


async def test_handle_pending_callback_sim_confirms_and_edits_message(monkeypatch):
    update = await _build_callback_update("pend:sim:abc123")
    context = Mock()
    resolve_pending_mock = AsyncMock(return_value="confirmada")
    monkeypatch.setattr(pending_handler, "resolve_pending", resolve_pending_mock)

    await pending_handler.handle_pending_callback(update, context)

    resolve_pending_mock.assert_awaited_once_with(42, "abc123", "sim")
    update.callback_query.edit_message_text.assert_awaited_once_with("✅ Confirmado e salvo.")


async def test_handle_pending_callback_nao_discards_and_edits_message(monkeypatch):
    update = await _build_callback_update("pend:nao:abc123")
    context = Mock()
    monkeypatch.setattr(pending_handler, "resolve_pending", AsyncMock(return_value="descartada"))

    await pending_handler.handle_pending_callback(update, context)

    update.callback_query.edit_message_text.assert_awaited_once_with("🚫 Descartado — não foi salvo.")


async def test_handle_pending_callback_already_resolved(monkeypatch):
    update = await _build_callback_update("pend:sim:abc123")
    context = Mock()
    monkeypatch.setattr(pending_handler, "resolve_pending", AsyncMock(return_value="ja_resolvida"))

    await pending_handler.handle_pending_callback(update, context)

    update.callback_query.edit_message_text.assert_awaited_once_with("Essa pendência já tinha sido resolvida antes.")
```

**Critério de aceitação:** os 6 testes passam, nenhuma chamada real à API do Telegram (tudo mockado).

## T8 — Handlers existentes: idempotência + mensagens de pendência

**`handlers/text_handler.py` — antes:**
```python
from telegram import Update
from telegram.ext import ContextTypes

from services.message_service import format_message, split_message
from services.nlp_service import extract_text_transactions
from services.transaction_service import save_transactions


async def get_message(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    text = update.message.text
    transactions = await extract_text_transactions(text)

    if not transactions:
        await update.message.reply_text(
            "Não foi identificada nenhuma transação nessa mensagem."
            " Tente algo como 'Gastei 30 reais no mercado'"
        )
        return

    results = await save_transactions(transactions, user_id)

    msg = format_message(results)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
```

**Depois:**
```python
from telegram import Update
from telegram.ext import ContextTypes

from handlers.pending_handler import build_confirmation_keyboard
from services.message_service import format_message, format_pending_message, split_message
from services.nlp_service import extract_text_transactions
from services.transaction_service import claim_update, save_transactions


async def get_message(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    if not await claim_update(user_id, update.update_id):
        return

    text = update.message.text
    transactions = await extract_text_transactions(text)

    if not transactions:
        await update.message.reply_text(
            "Não foi identificada nenhuma transação nessa mensagem."
            " Tente algo como 'Gastei 30 reais no mercado'"
        )
        return

    results = await save_transactions(transactions, user_id)

    msg = format_message(results)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")

    for r in results:
        if r.pendencia:
            await update.message.reply_text(
                format_pending_message(r.pendencia),
                reply_markup=build_confirmation_keyboard(r.pendencia.id),
            )
```

**Mesma mudança em `handlers/photo_handler.py` e `handlers/pdf_handler.py`**: adicionar `if not await claim_update(user_id, update.update_id): return` logo após capturar `user_id` (antes de qualquer download/upload/OCR — evita chamar Bedrock/S3 de novo numa reentrega), e o mesmo loop `for r in results: if r.pendencia: ...` depois de `save_transactions`/antes de terminar o handler. Import de `claim_update`, `build_confirmation_keyboard` e `format_pending_message` seguindo o mesmo padrão do `text_handler.py`.

**Teste** (`tests/handlers/test_text_handler.py`, `test_photo_handler.py`, `test_pdf_handler.py` — adicionar):
```python
async def test_already_processed_update_skips_extraction(monkeypatch):
    update = _build_update()
    update.update_id = 999
    context = Mock()
    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=False))
    extract_text_transactions = AsyncMock()
    monkeypatch.setattr(text_handler, "extract_text_transactions", extract_text_transactions)

    await text_handler.get_message(update, context)

    extract_text_transactions.assert_not_awaited()
    update.message.reply_text.assert_not_awaited()


async def test_pending_result_sends_extra_message_with_keyboard(monkeypatch):
    update = _build_update()
    update.update_id = 1
    context = Mock()
    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=True))
    monkeypatch.setattr(text_handler, "extract_text_transactions", AsyncMock(return_value=["transacao-fake"]))
    pendencia_fake = Mock(id="abc123")
    resultado_fake = Mock(pendencia=pendencia_fake)
    monkeypatch.setattr(text_handler, "save_transactions", AsyncMock(return_value=[resultado_fake]))
    monkeypatch.setattr(text_handler, "format_message", Mock(return_value="resumo"))
    monkeypatch.setattr(text_handler, "format_pending_message", Mock(return_value="texto pendencia"))

    await text_handler.get_message(update, context)

    calls = update.message.reply_text.call_args_list
    assert any(call.args[0] == "texto pendencia" for call in calls)
```
(ajustar `_build_update` de cada arquivo de teste para incluir `update.update_id = <algum inteiro>`; testes equivalentes em `test_photo_handler.py`/`test_pdf_handler.py`, adaptando aos mocks de `_storage`/`extract_document_data` já existentes nesses arquivos)

**Critério de aceitação:** testes novos passam; testes existentes de happy-path continuam passando (ajustar apenas o `monkeypatch` de `claim_update` para `AsyncMock(return_value=True)` nos testes que já existiam, senão a nova guarda os bloqueia).

## T9 — `main.py`

**Antes:**
```python
import asyncio

from telegram.ext import Application, MessageHandler, filters

from handlers.pdf_handler import get_pdf
from handlers.photo_handler import get_photo
from handlers.text_handler import get_message
from run_polling.config import BOT_TOKEN, DB_BACKEND
from database.connection import init_db


def main():
    if DB_BACKEND == "sqlite":
        asyncio.run(init_db())

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, get_message))
    app.add_handler(MessageHandler(filters.PHOTO, get_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, get_pdf))
    print("Bot rodando... aguardando mensagens.")
    app.run_polling()
```

**Depois** (`CommandHandler`/`CallbackQueryHandler` registrados **antes** do `MessageHandler(filters.TEXT, ...)` — ordem importa: o primeiro handler que casa processa o update e para a propagação, então `/pendencias` precisa ser capturado pelo `CommandHandler` antes de cair no `MessageHandler` de extração):
```python
import asyncio

from telegram.ext import Application, CallbackQueryHandler, CommandHandler, MessageHandler, filters

from handlers.pdf_handler import get_pdf
from handlers.pending_handler import get_pendencias, handle_pending_callback
from handlers.photo_handler import get_photo
from handlers.text_handler import get_message
from run_polling.config import BOT_TOKEN, DB_BACKEND
from database.connection import init_db


def main():
    if DB_BACKEND == "sqlite":
        asyncio.run(init_db())

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("pendencias", get_pendencias))
    app.add_handler(CallbackQueryHandler(handle_pending_callback, pattern=r"^pend:"))
    app.add_handler(MessageHandler(filters.TEXT, get_message))
    app.add_handler(MessageHandler(filters.PHOTO, get_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, get_pdf))
    print("Bot rodando... aguardando mensagens.")
    app.run_polling()
```

**Sem teste automatizado** (mesmo padrão do projeto — `main.py` não tem suíte própria, é conectado via `run_polling` real). Validado no Cenário de Teste Manual abaixo.

## T10 — Broadcast em `docs/PATTERNS.md`

Adicionar em "Decisões Estabelecidas":

```markdown
### Pendência de confirmação é um Item persistido (`PENDENTE#`), nunca em memória de processo

Quando uma transação candidata não pode ser classificada como `nova` com certeza determinística (colisão de fingerprint exato ou similaridade textual dentro da janela de dedup), o sistema grava uma pendência de confirmação como Item na mesma tabela (`sortKey = "PENDENTE#{uuid4().hex}"`, mesmo padrão de `ConfigItem`) em vez de decidir sozinho (bloquear ou salvar) ou guardar em `context.user_data`. A pendência nunca expira sozinha — só sai do estado "pendente" por confirmação explícita do usuário (botões inline). Esse padrão deve ser reaproveitado por qualquer feature futura que precise de "algo aguardando decisão do usuário, que sobrevive a restart" (ex.: uma eventual extensão do `CONTEXT003`, edição de transação). Origem: `docs/analysis/INV008-confirmacao-duplicata-exata.md` / `docs/specs/SPEC010-confirmacao-duplicata-exata.md` / `docs/tasks/TASKS010-confirmacao-duplicata-exata.md`.

### Timestamp de chegada (`criadoEm`) é atributo de Item/Entity, nunca do DTO `Transacao`

Quando uma feature precisa do momento real de chegada de uma mensagem (não a data de negócio, que é só `date`), o timestamp vive como atributo adicional no Item do DynamoDB (`criadoEm`, ISO datetime UTC), nunca em `models.Transacao` — mantém a separação DTO/Entity já estabelecida. Itens gravados antes dessa mudança não têm esse atributo; qualquer leitura que dependa dele precisa de um fallback explícito (usado aqui: meia-noite UTC da própria `data` de negócio). Origem: `docs/tasks/TASKS010-confirmacao-duplicata-exata.md`.

### Idempotência de entrega (`update_id`/`message_id`) usa TTL nativo do DynamoDB, não uma tabela/limpeza própria

Para descartar reentrega técnica de uma mensagem já processada (retry de webhook, restart no meio do processamento) sem reter esse controle para sempre, usa-se um Item (`sortKey = "PROCESSADO#{update_id}"`) com o atributo de TTL nativo da tabela (`expiraEm`, epoch seconds) — a tabela precisa ter TTL habilitado nesse atributo (`aws dynamodb update-time-to-live`, ação manual). Nunca confundir com a dedup de conteúdo (`DUPLICATA_EXATA`/`SUSPEITA`) — são eixos ortogonais. Origem: `docs/tasks/TASKS010-confirmacao-duplicata-exata.md`.
```

## Ordem de Execução

T1 → T2 (ambas manuais/independentes, podem rodar em paralelo entre si, mas antes de T4 rodar de verdade em produção — os testes automatizados de T4 não dependem delas, só o uso real do bot depende) → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10.

`T3` e `T4` são pré-requisito de tudo depois (schema e lógica de repository). `T7` precisa de `T5`/`T6` prontos (usa `get_pending`/`resolve_pending`/`format_pending_message`). `T8` precisa de `T7` (`build_confirmation_keyboard`). `T9` precisa de `T7`/`T8`.

## Regra do Escoteiro / Testes

- Toda lógica pura nova (`_transacao_to_map`, `_criado_em_or_fallback`, cálculo de intervalo em `format_pending_message`) tem teste automatizado, seguindo TDD.
- Nenhuma chamada real a AWS/Telegram entra em teste automatizado — só client/objetos mockados, mesmo padrão já usado em todo o projeto.
- `_transacao_to_map` é extraído como função pura reaproveitada tanto na gravação normal quanto no embutido da pendência (`transacao`/`similares`) — elimina a duplicação que existia antes (montar o dict do Item era feito inline em `_save_one`).

## Notas de Implementação (registradas durante a execução)

- **T4**: a lista de "testes a reescrever" do TASKS enumerou 4 testes afetados, mas 2 outros testes já existentes (`test_save_transaction_with_categoria_includes_attribute_in_item`, `test_put_item_other_error_raises_repository_error`) também quebravam com a nova lógica — `_save_one` agora chama `table.get_item` antes de `table.query`/`table.put_item`, e sem mockar `get_item` o `Mock()` default não é subscriptable (`TypeError`, não uma falha de asserção). Corrigido inline com `table.get_item.return_value = {}`, mesmo padrão já prescrito pelo TASKS para os testes vizinhos — ajuste mecânico de mock, sem decisão de design nova, sem bump de versão (confirmado com o advisor antes de aplicar).
- **T4**: `test_cafe_bolo_cafe_same_day_second_cafe_is_duplicata_exata` também teve a asserção `table.query.call_count == 2` atualizada para `== 4` — consequência mecânica de `_find_similar` agora fazer duas Queries (janela real + `PENDENTE#`) por chamada que não bate exata, não uma mudança de design.
- **T7**: o "Critério de aceitação" do T7 diz "os 6 testes passam", mas o corpo do T7 especifica só 5 funções de teste (`test_get_pendencias_no_pending_replies_with_empty_message`, `test_get_pendencias_sends_one_message_per_pending_with_keyboard`, `test_handle_pending_callback_sim_confirms_and_edits_message`, `test_handle_pending_callback_nao_discards_and_edits_message`, `test_handle_pending_callback_already_resolved`). Provável erro de contagem no doc — a lista de casos é completa e inequívoca, implementados os 5.

## Cenários de Teste Manual

1. Enviar "gastei 30 reais no mercado" duas vezes seguidas no mesmo dia → segunda mensagem gera uma pendência com botões "Sim"/"Não" (não bloqueia mais em silêncio).
2. Enviar "gastei 30 reais no mercado" e depois "gastei mesmo 30 reais no mercado" → segunda mensagem também gera pendência (LLM tende a extrair a mesma `descricao` curta).
3. Tocar "Sim" numa pendência → transação aparece nas próximas consultas/totais; tocar "Sim" de novo na mesma mensagem (duplo toque) → segunda tentativa mostra "já tinha sido resolvida".
4. Tocar "Não" numa pendência → transação não aparece nos totais; mensagem confirma o descarte.
5. Enviar uma foto de extrato com várias transações, algumas repetidas de transações já registradas → mensagem-resumo mostra as `nova` com valores, e uma mensagem separada por transação pendente, cada uma com seus próprios botões.
6. Rodar `/pendencias` sem nenhuma pendência aberta → "Nenhuma pendência em aberto. 🎉".
7. Criar uma pendência, reiniciar o bot (`Ctrl+C` e `python main.py` de novo), rodar `/pendencias` → a pendência continua listada.
8. Reenviar a mesma mensagem do Telegram (ex.: usando um cliente que force reentrega, ou simular restart no meio do processamento) → segunda entrega não gera nova extração nem pendência duplicada.

## Fora de Escopo

- Push proativo semanal (`JobQueue`/`APScheduler`) — task futura, apoiada nesta mesma fundação de dados.
- Qualquer parte da Fase 6b (agente de conselho).
- Implementação em `SqliteTransactionRepository`.
- Migração de pendências/dados históricos.

## Notas de Execução

- **Verificação automatizada**: `pytest` na raiz — 141/141 testes passam (0 falhas), incluindo os 27 testes novos/reescritos desta task. Sem chamada real a AWS/Telegram em nenhum teste.
- **T1 confirmado na AWS real**: usuário rodou `aws iam create-policy-version`. Verificado nesta sessão via `aws iam get-policy` (profile `default`, ação de bootstrap de conta) → `DefaultVersionId: v7`; `aws iam get-policy-version --version-id v7` confirma `dynamodb:DeleteItem` no `Sid` `DynamoDBReadWriteTransacoesGuardiaoDev`.
- **T2 confirmado na AWS real**: usuário rodou `aws dynamodb update-time-to-live`. Verificado nesta sessão via `aws dynamodb describe-time-to-live --table-name GuardiaoFinanceiro-Transacoes-dev --region us-east-2` (profile `default` — `guardiao-dev` não tem `dynamodb:DescribeTimeToLive`) → `"TimeToLiveStatus": "ENABLED"`, `"AttributeName": "expiraEm"`.
- **Cenários de Teste Manual 1-8: todos executados pelo usuário contra o bot real (Telegram + DynamoDB), todos passaram** conforme relatado após subir o bot com `python main.py`. Nenhuma divergência de comportamento reportada.

## Validação Final (contra `SPEC010`)

- R1-R2 (idempotência): T4 (`try_claim_update`) + T8 (guarda nos 3 handlers).
- R3-R6 (reclassificação + busca ampliada): T4 (`_find_exact`/`_find_similar`/`_create_pending`).
- R7-R9 (persistência, nunca expira, sobrevive a restart): T4 (Item `PENDENTE#`, sem TTL nesse Item — só o `PROCESSADO#` tem TTL).
- R10 (lote não bloqueia): T4 (`save_transactions` processa cada item independentemente, já era assim, mantido).
- R11-R14 (superfícies, botões, resolução): T7 (`/pendencias` + callback), T8 (mensagem imediata no lote).
- R15 (calibração por tempo): T6 (`format_pending_message`).

Todas as Perguntas em Aberto do `INV008` foram respondidas (nas Decisões de Produto do próprio INV, no `SPEC010`, ou nas Decisões vinculantes/refinamentos deste TASKS) — nenhuma sobra para a implementação decidir sozinha.
