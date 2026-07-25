# NLP Query — Totais por Período: Plano de Implementação

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Permitir que o usuário consulte entradas, saídas e saldo de um período em linguagem natural via bot Telegram.

**Architecture:** Uma chamada ao Gemini classifica o intent da mensagem (`intent_service`); se for `"query"`, uma segunda chamada extrai o período (`query_service`) e a agregação SQL retorna os totais; o `text_handler` roteia os três caminhos (transaction / query / unknown).

**Tech Stack:** Python 3.12, google-genai 2.10 (Gemini 2.5-flash), SQLAlchemy async, aiosqlite, pytest 8, pytest-asyncio.

---

## Estrutura de Arquivos

| Ação | Arquivo | Responsabilidade |
|---|---|---|
| Criar | `services/intent_service.py` | Call 1 Gemini: retorna `"transaction" \| "query" \| "unknown"` |
| Criar | `services/query_service.py` | Call 2b Gemini: extrai período + formata resumo |
| Modificar | `repository/transaction.py` | Adiciona `get_totals_by_period()` |
| Modificar | `services/transaction_service.py` | Adiciona `get_totals()` |
| Modificar | `handlers/text_handler.py` | Roteamento por intent (3 caminhos) |
| Criar | `tests/conftest.py` | Fixtures compartilhadas: sessão DB em memória, transação mock |
| Criar | `tests/repository/test_transaction.py` | Testes de `get_totals_by_period()` |
| Criar | `tests/services/test_transaction_service.py` | Testes de `get_totals()` |
| Criar | `tests/services/test_intent_service.py` | Testes de `classify()` |
| Criar | `tests/services/test_query_service.py` | Testes de `resolve_query()` e `_format_summary()` |
| Criar | `tests/handlers/test_text_handler.py` | Testes de roteamento do handler |

---

## Task 1: Configurar pytest + fixtures de banco em memória

**Files:**
- Criar: `pytest.ini`
- Criar: `tests/__init__.py`
- Criar: `tests/conftest.py`
- Criar: `tests/repository/__init__.py`
- Criar: `tests/services/__init__.py`
- Criar: `tests/handlers/__init__.py`

- [ ] **Step 1: Instalar pytest e pytest-asyncio**

```bash
source venv/bin/activate
pip install pytest pytest-asyncio
```

Esperado: instalação sem erros.

- [ ] **Step 2: Criar `pytest.ini`**

```ini
[pytest]
asyncio_mode = auto
```

- [ ] **Step 3: Criar `tests/__init__.py` e subdiretórios**

```bash
mkdir -p tests/repository tests/services tests/handlers
touch tests/__init__.py tests/repository/__init__.py tests/services/__init__.py tests/handlers/__init__.py
```

- [ ] **Step 4: Criar `tests/conftest.py`**

```python
from datetime import date

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.base import Base
from models import Transacao


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
def mock_transactions():
    return [
        Transacao(
            data=date(2026, 6, 28),
            descricao="teste",
            valor=50.0,
            tipo="saida",
            categoria="alimentação",
        )
    ]
```

- [ ] **Step 5: Verificar que pytest descobre os diretórios**

```bash
source venv/bin/activate && pytest tests/ --collect-only
```

Esperado: `no tests ran` sem erros de import.

- [ ] **Step 6: Commit**

```bash
git add pytest.ini tests/
git commit -m "🧪 test: configura pytest com asyncio e fixtures de banco em memória"
```

---

## Task 2: `get_totals_by_period()` no repository (TDD)

**Files:**
- Modificar: `repository/transaction.py`
- Criar: `tests/repository/test_transaction.py`

- [ ] **Step 1: Escrever os testes**

Criar `tests/repository/test_transaction.py`:

```python
from datetime import date

from database.entities.transaction import TransactionEntity
from repository.transaction import TransactionRepository


async def _insert(session, user_id: int, tipo: str, valor: float, data: date) -> None:
    session.add(TransactionEntity(
        telegram_user_id=user_id,
        data=data,
        descricao="test",
        valor=valor,
        tipo=tipo,
        categoria="",
    ))
    await session.commit()


async def test_get_totals_sums_entradas_and_saidas(db_session):
    await _insert(db_session, 1, "entrada", 1000.0, date(2026, 6, 10))
    await _insert(db_session, 1, "saida", 300.0, date(2026, 6, 15))
    await _insert(db_session, 1, "saida", 150.0, date(2026, 6, 20))

    repo = TransactionRepository(db_session)
    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 1000.0, "saidas": 450.0}


async def test_get_totals_ignores_other_users(db_session):
    await _insert(db_session, 1, "entrada", 500.0, date(2026, 6, 10))
    await _insert(db_session, 2, "entrada", 9999.0, date(2026, 6, 10))

    repo = TransactionRepository(db_session)
    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 500.0, "saidas": 0.0}


async def test_get_totals_ignores_transactions_outside_range(db_session):
    await _insert(db_session, 1, "saida", 200.0, date(2026, 5, 31))
    await _insert(db_session, 1, "saida", 100.0, date(2026, 6, 15))
    await _insert(db_session, 1, "saida", 300.0, date(2026, 7, 1))

    repo = TransactionRepository(db_session)
    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 0.0, "saidas": 100.0}


async def test_get_totals_returns_zeros_when_no_transactions(db_session):
    repo = TransactionRepository(db_session)
    result = await repo.get_totals_by_period(1, date(2026, 6, 1), date(2026, 6, 30))

    assert result == {"entradas": 0.0, "saidas": 0.0}
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

```bash
source venv/bin/activate && pytest tests/repository/test_transaction.py -v
```

Esperado: `AttributeError: 'TransactionRepository' object has no attribute 'get_totals_by_period'`

- [ ] **Step 3: Implementar `get_totals_by_period()` em `repository/transaction.py`**

Alterar o arquivo para:

```python
from datetime import date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database.entities.transaction import TransactionEntity
from models import Transacao


class TransactionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save_transactions(self, transactions: list[Transacao], telegram_user_id: int) -> None:
        for transaction in transactions:
            self.session.add(TransactionEntity(
                telegram_user_id=telegram_user_id,
                data=transaction.data,
                descricao=transaction.descricao,
                valor=transaction.valor,
                tipo=transaction.tipo,
                categoria=transaction.categoria,
            ))
        await self.session.commit()

    async def find_by_user(self, telegram_user_id: int) -> list[Transacao]:
        result = await self.session.execute(
            select(TransactionEntity).where(
                TransactionEntity.telegram_user_id == telegram_user_id
            )
        )
        entities = result.scalars().all()
        return [
            Transacao(
                data=e.data,
                descricao=e.descricao,
                valor=e.valor,
                tipo=e.tipo,
                categoria=e.categoria,
            )
            for e in entities
        ]

    async def get_totals_by_period(
        self, telegram_user_id: int, start: date, end: date
    ) -> dict[str, float]:
        result_entradas = await self.session.execute(
            select(func.sum(TransactionEntity.valor)).where(
                TransactionEntity.telegram_user_id == telegram_user_id,
                TransactionEntity.tipo == "entrada",
                TransactionEntity.data >= start,
                TransactionEntity.data <= end,
            )
        )
        result_saidas = await self.session.execute(
            select(func.sum(TransactionEntity.valor)).where(
                TransactionEntity.telegram_user_id == telegram_user_id,
                TransactionEntity.tipo == "saida",
                TransactionEntity.data >= start,
                TransactionEntity.data <= end,
            )
        )
        return {
            "entradas": result_entradas.scalar() or 0.0,
            "saidas": result_saidas.scalar() or 0.0,
        }
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

```bash
source venv/bin/activate && pytest tests/repository/test_transaction.py -v
```

Esperado: `4 passed`

- [ ] **Step 5: Commit**

```bash
git add repository/transaction.py tests/repository/test_transaction.py
git commit -m "✨ feat: adiciona get_totals_by_period no repository"
```

---

## Task 3: `get_totals()` no transaction_service (TDD)

**Files:**
- Modificar: `services/transaction_service.py`
- Criar: `tests/services/test_transaction_service.py`

- [ ] **Step 1: Escrever o teste**

Criar `tests/services/test_transaction_service.py`:

```python
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from services.transaction_service import get_totals


async def test_get_totals_delegates_to_repository():
    expected = {"entradas": 500.0, "saidas": 200.0}
    mock_repo = MagicMock()
    mock_repo.get_totals_by_period = AsyncMock(return_value=expected)
    mock_session = MagicMock()
    mock_session.__aenter__ = AsyncMock(return_value=mock_session)
    mock_session.__aexit__ = AsyncMock(return_value=None)

    with patch("services.transaction_service.async_session", return_value=mock_session), \
         patch("services.transaction_service.TransactionRepository", return_value=mock_repo):
        result = await get_totals(1, date(2026, 6, 1), date(2026, 6, 30))

    mock_repo.get_totals_by_period.assert_called_once_with(1, date(2026, 6, 1), date(2026, 6, 30))
    assert result == expected
```

- [ ] **Step 2: Rodar o teste e confirmar que falha**

```bash
source venv/bin/activate && pytest tests/services/test_transaction_service.py -v
```

Esperado: `ImportError` ou `AttributeError: module has no attribute 'get_totals'`

- [ ] **Step 3: Implementar `get_totals()` em `services/transaction_service.py`**

```python
from datetime import date

from database.connection import async_session
from models import Transacao
from repository.transaction import TransactionRepository


async def save_transactions(transactions: list[Transacao], telegram_user_id: int) -> None:
    async with async_session() as session:
        repository = TransactionRepository(session)
        await repository.save_transactions(transactions, telegram_user_id)


async def get_transactions(telegram_user_id: int) -> list[Transacao]:
    async with async_session() as session:
        repository = TransactionRepository(session)
        return await repository.find_by_user(telegram_user_id)


async def get_totals(
    telegram_user_id: int, start: date, end: date
) -> dict[str, float]:
    async with async_session() as session:
        repository = TransactionRepository(session)
        return await repository.get_totals_by_period(telegram_user_id, start, end)
```

- [ ] **Step 4: Rodar o teste e confirmar que passa**

```bash
source venv/bin/activate && pytest tests/services/test_transaction_service.py -v
```

Esperado: `1 passed`

- [ ] **Step 5: Commit**

```bash
git add services/transaction_service.py tests/services/test_transaction_service.py
git commit -m "✨ feat: adiciona get_totals no transaction_service"
```

---

## Task 4: `intent_service.py` — classificar intent (TDD)

**Files:**
- Criar: `services/intent_service.py`
- Criar: `tests/services/test_intent_service.py`

- [ ] **Step 1: Escrever os testes**

Criar `tests/services/test_intent_service.py`:

```python
from unittest.mock import MagicMock, patch

from services.intent_service import classify


async def test_classify_returns_transaction_for_expense():
    mock_response = MagicMock()
    mock_response.text = '{"intent": "transaction"}'
    with patch("services.intent_service.client.models.generate_content", return_value=mock_response):
        result = await classify("gastei 50 no mercado")
    assert result == "transaction"


async def test_classify_returns_query_for_totals_question():
    mock_response = MagicMock()
    mock_response.text = '{"intent": "query"}'
    with patch("services.intent_service.client.models.generate_content", return_value=mock_response):
        result = await classify("quanto gastei esse mês?")
    assert result == "query"


async def test_classify_returns_unknown_for_greeting():
    mock_response = MagicMock()
    mock_response.text = '{"intent": "unknown"}'
    with patch("services.intent_service.client.models.generate_content", return_value=mock_response):
        result = await classify("oi tudo bem?")
    assert result == "unknown"
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

```bash
source venv/bin/activate && pytest tests/services/test_intent_service.py -v
```

Esperado: `ModuleNotFoundError: No module named 'services.intent_service'`

- [ ] **Step 3: Criar `services/intent_service.py`**

```python
import json

from google import genai
from google.genai import types

from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def classify(text: str) -> str:
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            'Classifique a intenção da mensagem em uma das três categorias:\n'
            '"transaction": registrar gasto ou recebimento '
            '(ex: "gastei 50 no mercado", "recebi 1000 de salário")\n'
            '"query": consultar resumo financeiro, totais ou saldo '
            '(ex: "quanto gastei esse mês?", "qual meu saldo em junho?")\n'
            '"unknown": qualquer outra coisa '
            '(ex: saudações, perguntas não financeiras)\n\n'
            f'Mensagem: "{text}"\n\n'
            'Responda APENAS com JSON: {"intent": "transaction" | "query" | "unknown"}'
        ),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    data = json.loads(response.text)
    return data["intent"]
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

```bash
source venv/bin/activate && pytest tests/services/test_intent_service.py -v
```

Esperado: `3 passed`

- [ ] **Step 5: Commit**

```bash
git add services/intent_service.py tests/services/test_intent_service.py
git commit -m "✨ feat: adiciona intent_service para classificar mensagens"
```

---

## Task 5: `query_service.py` — extrair período e formatar resposta (TDD)

**Files:**
- Criar: `services/query_service.py`
- Criar: `tests/services/test_query_service.py`

- [ ] **Step 1: Escrever os testes**

Criar `tests/services/test_query_service.py`:

```python
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from services.query_service import _format_summary, resolve_query


async def test_resolve_query_returns_clarification_when_period_not_identified():
    mock_response = MagicMock()
    mock_response.text = '{"periodo_identificado": false, "inicio": null, "fim": null}'
    with patch("services.query_service.client.models.generate_content", return_value=mock_response):
        result = await resolve_query("quanto gastei?", telegram_user_id=1)
    assert result == "Qual período você quer consultar? Ex: 'esse mês', 'junho', 'este ano'."


async def test_resolve_query_returns_formatted_summary_when_period_identified():
    mock_response = MagicMock()
    mock_response.text = '{"periodo_identificado": true, "inicio": "2026-06-01", "fim": "2026-06-30"}'
    mock_totals = {"entradas": 1000.0, "saidas": 400.0}
    with patch("services.query_service.client.models.generate_content", return_value=mock_response), \
         patch("services.query_service.get_totals", new=AsyncMock(return_value=mock_totals)):
        result = await resolve_query("quanto gastei em junho?", telegram_user_id=1)
    assert "junho/2026" in result
    assert "R$ 1000.00" in result
    assert "R$ 400.00" in result
    assert "R$ 600.00" in result


def test_format_summary_same_month_uses_month_name():
    totals = {"entradas": 1000.0, "saidas": 400.0}
    result = _format_summary(date(2026, 6, 1), date(2026, 6, 30), totals)
    assert "junho/2026" in result
    assert "R$ 1000.00" in result
    assert "R$ 400.00" in result
    assert "R$ 600.00" in result


def test_format_summary_cross_month_uses_date_range():
    totals = {"entradas": 500.0, "saidas": 200.0}
    result = _format_summary(date(2026, 6, 15), date(2026, 7, 15), totals)
    assert "15/06/2026 a 15/07/2026" in result
    assert "R$ 500.00" in result
    assert "R$ 200.00" in result
    assert "R$ 300.00" in result


def test_format_summary_negative_saldo():
    totals = {"entradas": 100.0, "saidas": 400.0}
    result = _format_summary(date(2026, 6, 1), date(2026, 6, 30), totals)
    assert "R$ -300.00" in result
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

```bash
source venv/bin/activate && pytest tests/services/test_query_service.py -v
```

Esperado: `ModuleNotFoundError: No module named 'services.query_service'`

- [ ] **Step 3: Criar `services/query_service.py`**

```python
import json
from datetime import date

from google import genai
from google.genai import types

from run_polling.config import GEMINI_API_KEY
from services.transaction_service import get_totals

client = genai.Client(api_key=GEMINI_API_KEY)

_MONTHS_PT = {
    1: "janeiro", 2: "fevereiro", 3: "março", 4: "abril",
    5: "maio", 6: "junho", 7: "julho", 8: "agosto",
    9: "setembro", 10: "outubro", 11: "novembro", 12: "dezembro",
}


async def resolve_query(text: str, telegram_user_id: int) -> str:
    today = date.today().isoformat()
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            f"A data de hoje é {today}. "
            f'O usuário quer consultar suas finanças: "{text}". '
            "Extraia o período financeiro mencionado e retorne: "
            '{"periodo_identificado": true, "inicio": "YYYY-MM-DD", "fim": "YYYY-MM-DD"} '
            "ou, se não houver período identificável: "
            '{"periodo_identificado": false, "inicio": null, "fim": null}'
        ),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    data = json.loads(response.text)

    if not data.get("periodo_identificado"):
        return "Qual período você quer consultar? Ex: 'esse mês', 'junho', 'este ano'."

    start = date.fromisoformat(data["inicio"])
    end = date.fromisoformat(data["fim"])
    totals = await get_totals(telegram_user_id, start, end)
    return _format_summary(start, end, totals)


def _format_summary(start: date, end: date, totals: dict[str, float]) -> str:
    if start.month == end.month and start.year == end.year:
        period_label = f"{_MONTHS_PT[start.month]}/{start.year}"
    else:
        period_label = f"{start.strftime('%d/%m/%Y')} a {end.strftime('%d/%m/%Y')}"

    entradas = totals["entradas"]
    saidas = totals["saidas"]
    saldo = entradas - saidas

    return (
        f"📊 Resumo de {period_label}\n\n"
        f"🟢 Entradas: R$ {entradas:.2f}\n"
        f"🔴 Saídas:   R$ {saidas:.2f}\n"
        f"💰 Saldo:    R$ {saldo:.2f}"
    )
```

- [ ] **Step 4: Rodar os testes e confirmar que passam**

```bash
source venv/bin/activate && pytest tests/services/test_query_service.py -v
```

Esperado: `5 passed`

- [ ] **Step 5: Commit**

```bash
git add services/query_service.py tests/services/test_query_service.py
git commit -m "✨ feat: adiciona query_service para consultas de totais por período"
```

---

## Task 6: Atualizar `text_handler.py` — roteamento por intent (TDD)

**Files:**
- Modificar: `handlers/text_handler.py`
- Criar: `tests/handlers/test_text_handler.py`

- [ ] **Step 1: Escrever os testes**

Criar `tests/handlers/test_text_handler.py`:

```python
from unittest.mock import AsyncMock, MagicMock, patch

from handlers.text_handler import get_message


def _make_update(text: str, user_id: int = 1):
    update = MagicMock()
    update.effective_user.id = user_id
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


async def test_transaction_intent_saves_and_replies(mock_transactions):
    update = _make_update("gastei 50 no mercado")
    with patch("handlers.text_handler.classify", new=AsyncMock(return_value="transaction")), \
         patch("handlers.text_handler.extract_text_transactions", new=AsyncMock(return_value=mock_transactions)), \
         patch("handlers.text_handler.save_transactions", new=AsyncMock()):
        await get_message(update, MagicMock())
    update.message.reply_text.assert_called_once()


async def test_transaction_intent_with_empty_result_replies_help():
    update = _make_update("mensagem que não vira transação")
    with patch("handlers.text_handler.classify", new=AsyncMock(return_value="transaction")), \
         patch("handlers.text_handler.extract_text_transactions", new=AsyncMock(return_value=[])):
        await get_message(update, MagicMock())
    call_text = update.message.reply_text.call_args[0][0]
    assert "transação" in call_text.lower()


async def test_query_intent_calls_resolve_query_and_replies():
    update = _make_update("quanto gastei esse mês?")
    with patch("handlers.text_handler.classify", new=AsyncMock(return_value="query")), \
         patch("handlers.text_handler.resolve_query", new=AsyncMock(return_value="📊 Resumo de junho/2026\n...")):
        await get_message(update, MagicMock())
    update.message.reply_text.assert_called_once_with("📊 Resumo de junho/2026\n...")


async def test_unknown_intent_replies_help_message():
    update = _make_update("oi tudo bem?")
    with patch("handlers.text_handler.classify", new=AsyncMock(return_value="unknown")):
        await get_message(update, MagicMock())
    update.message.reply_text.assert_called_once()
    call_text = update.message.reply_text.call_args[0][0]
    assert "registrar" in call_text.lower() or "consultar" in call_text.lower()
```

- [ ] **Step 2: Rodar os testes e confirmar que falham**

```bash
source venv/bin/activate && pytest tests/handlers/test_text_handler.py -v
```

Esperado: falhas por `ImportError` ou por `classify` e `resolve_query` não existirem no handler.

- [ ] **Step 3: Substituir o conteúdo de `handlers/text_handler.py`**

```python
from telegram import Update
from telegram.ext import ContextTypes

from services.intent_service import classify
from services.message_service import format_message, split_message
from services.nlp_service import extract_text_transactions
from services.query_service import resolve_query
from services.transaction_service import save_transactions


async def get_message(update: Update, context: ContextTypes):
    user_id = update.effective_user.id
    text = update.message.text

    intent = await classify(text)

    if intent == "transaction":
        transactions = await extract_text_transactions(text)
        if not transactions:
            await update.message.reply_text(
                "Não foi identificada nenhuma transação nessa mensagem."
                " Tente algo como 'Gastei 30 reais no mercado'"
            )
            return
        await save_transactions(transactions, user_id)
        msg = format_message(transactions)
        for block in split_message(msg):
            await update.message.reply_text(block, parse_mode="HTML")

    elif intent == "query":
        result = await resolve_query(text, user_id)
        await update.message.reply_text(result)

    else:
        await update.message.reply_text(
            "Não entendi. Posso registrar transações ou consultar seu resumo financeiro.\n"
            "Exemplos:\n"
            "• 'Gastei 50 reais no mercado'\n"
            "• 'Quanto gastei esse mês?'"
        )
```

- [ ] **Step 4: Rodar todos os testes**

```bash
source venv/bin/activate && pytest tests/ -v
```

Esperado: todos os testes passam (repository + services + handlers).

- [ ] **Step 5: Commit**

```bash
git add handlers/text_handler.py tests/handlers/test_text_handler.py
git commit -m "✨ feat: adiciona roteamento por intent no text_handler"
```
