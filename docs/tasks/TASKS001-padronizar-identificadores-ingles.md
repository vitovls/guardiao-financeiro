---
type: TASKS
version: 1.0.0
author: Victor Veloso
date: 2026-06-28
status: Done
spec:
plan:
inv:
---

# TASKS001 — Padronizar identificadores para inglês

## Contexto

Todo código-fonte usa identificadores misturados (PT/EN). A decisão registrada em `CLAUDE.md` e `docs/PATTERNS.md` é que **todos os identificadores de código devem estar em inglês**. Este TASKS executa a padronização.

**Escopo:**
- Funções, métodos, variáveis, parâmetros e classes → inglês
- 3 arquivos renomeados via `git mv`
- Strings ao usuário (mensagens Telegram) → permanecem em PT
- Prompts ao Gemini → permanecem em PT
- Campos do modelo `Transacao` (`descricao`, `valor`, `tipo`, `categoria`) → **não mudam** (são chaves do JSON Gemini)
- Valores de domínio (`"entrada"`, `"saida"`) → **não mudam**
- `__tablename__ = "transacoes"` → **não muda** (artefato de banco)

**Sem testes configurados no projeto.** O critério de aceitação de cada T é: `python -c "import main"` executa sem erro de importação ao final.

---

## Progresso

- [x] T1 — Renomear arquivos com git mv
- [x] T2 — database/entities/transaction.py: renomear classe
- [x] T3 — repository/transaction.py: renomear classe, métodos e parâmetros
- [x] T4 — services/transaction_service.py: renomear funções e variáveis
- [x] T5 — services/auth_service.py: renomear função
- [x] T6 — services/message_service.py: renomear função e variáveis
- [x] T7 — services/nlp_service.py: renomear função e variáveis
- [x] T8 — services/ocr_service.py: renomear parâmetro e variável
- [x] T9 — Handlers: renomear variáveis e atualizar imports
- [x] T10 — Smoke test de importação

## Ordem de Execução

T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10

T1 deve ser o primeiro pois os demais dependem dos novos caminhos de arquivo.

---

## T1 — Renomear arquivos com git mv

**Critério de aceitação:** os três arquivos existem nos novos caminhos; os caminhos antigos não existem mais; `git status` mostra `renamed`.

```bash
git mv repository/transacao.py repository/transaction.py
git mv database/entities/transacao.py database/entities/transaction.py
git mv services/transacao_service.py services/transaction_service.py
```

Não editar o conteúdo neste passo — só renomear.

---

## T2 — `database/entities/transaction.py`: renomear classe

**Arquivo:** `database/entities/transaction.py`

**Antes:**
```python
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base


class TransacaoEntity(Base):
    __tablename__ = "transacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    usuario_telegram_id: Mapped[int] = mapped_column(Integer, index=True)

    data: Mapped[date] = mapped_column(Date)
    descricao: Mapped[str] = mapped_column(String)
    valor:  Mapped[float] = mapped_column(Float)
    tipo: Mapped[str] = mapped_column(String)
    categoria: Mapped[str] = mapped_column(String, default="")

    criado_em: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

**Depois:** apenas renomear a classe; tudo mais permanece idêntico.
```python
class TransactionEntity(Base):   # ← único change
    __tablename__ = "transacoes"  # ← não muda
    ...
```

**Também renomear:** coluna `usuario_telegram_id` → `telegram_user_id` (atributo Python; o nome da coluna no DB não precisa mudar — SQLAlchemy usa o nome do atributo por padrão, mas como não há dados em produção isso é seguro).

**Depois completo:**
```python
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column
from database.base import Base


class TransactionEntity(Base):
    __tablename__ = "transacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    telegram_user_id: Mapped[int] = mapped_column(Integer, index=True)

    data: Mapped[date] = mapped_column(Date)
    descricao: Mapped[str] = mapped_column(String)
    valor: Mapped[float] = mapped_column(Float)
    tipo: Mapped[str] = mapped_column(String)
    categoria: Mapped[str] = mapped_column(String, default="")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
```

---

## T3 — `repository/transaction.py`: renomear classe, métodos e parâmetros

**Arquivo:** `repository/transaction.py`

**Antes:**
```python
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database.entities.transacao import TransacaoEntity
from models import Transacao


class TransacaoRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def salvar_transacoes(self, transacoes: list[Transacao], usuario_telegram_id: int) -> None:
        for transacao in transacoes:
            self.session.add(TransacaoEntity(
                usuario_telegram_id=usuario_telegram_id,
                data=transacao.data,
                descricao=transacao.descricao,
                valor=transacao.valor,
                tipo=transacao.tipo,
                categoria=transacao.categoria,
            ))
        await self.session.commit()

    async def buscar_por_usuario(self, usuario_telegram_id: int) -> list[Transacao]:
        result = await self.session.execute(
            select(TransacaoEntity).where(
                TransacaoEntity.usuario_telegram_id == usuario_telegram_id
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
```

**Depois:**
```python
from sqlalchemy import select
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
```

---

## T4 — `services/transaction_service.py`: renomear funções e variáveis

**Arquivo:** `services/transaction_service.py`

**Antes:**
```python
from database.connection import async_session
from models import Transacao
from repository.transacao import TransacaoRepository


async def salvar_transacoes(transacoes: list[Transacao], usuario_telegram_id: int) -> None:
    async with async_session() as session:
        repositorio = TransacaoRepository(session)
        await repositorio.salvar_transacoes(transacoes, usuario_telegram_id)


async def buscar_transacoes(usuario_telegram_id: int) -> list[Transacao]:
    async with async_session() as session:
        repositorio = TransacaoRepository(session)
        return await repositorio.buscar_por_usuario(usuario_telegram_id)
```

**Depois:**
```python
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
```

---

## T5 — `services/auth_service.py`: renomear função

**Arquivo:** `services/auth_service.py`

**Antes:**
```python
def usuario_autorizado(user_id: int) -> bool:
    return True
```

**Depois:**
```python
def is_user_authorized(user_id: int) -> bool:
    return True
```

---

## T6 — `services/message_service.py`: renomear função e variáveis

**Arquivo:** `services/message_service.py`

**Antes:**
```python
from models import Transacao


def split_message(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]

    block = []
    lines = text.split("\n")
    cur = ""

    for linha in lines:
        if len(cur) + len(linha) + 1 > limit:
            block.append(cur)
            cur = linha
        else:
            cur = f"{cur}\n{linha}" if cur else linha

    if cur:
        block.append(cur)

    return block

def formatter_message(transactions: list[Transacao]) -> str:
    if not transactions:
        return "Não encontrei nenhuma transação nessa imagem."

    lines = ["<b>📊 Extrato processado</b>", ""]
    enter = 0.0
    leave = 0.0

    for t in transactions:
        emoji = "🟢" if t.tipo == "entrada" else "🔴"
        if t.tipo == "entrada":
            enter += t.valor
        else:
            leave += t.valor
        lines.append(f"{emoji} {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}")

    balance = enter - leave
    lines.append("")
    lines.append("<b>Resumo</b>")
    lines.append(f"🟢 Entradas: R$ {enter:.2f}")
    lines.append(f"🔴 Saídas: R$ {leave:.2f}")
    lines.append(f"💰 Saldo: R$ {balance:.2f}")

    return "\n".join(lines)
```

**Depois:**
```python
from models import Transacao


def split_message(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]

    block = []
    lines = text.split("\n")
    cur = ""

    for line in lines:
        if len(cur) + len(line) + 1 > limit:
            block.append(cur)
            cur = line
        else:
            cur = f"{cur}\n{line}" if cur else line

    if cur:
        block.append(cur)

    return block


def format_message(transactions: list[Transacao]) -> str:
    if not transactions:
        return "Não encontrei nenhuma transação nessa imagem."

    lines = ["<b>📊 Extrato processado</b>", ""]
    income_total = 0.0
    expense_total = 0.0

    for t in transactions:
        emoji = "🟢" if t.tipo == "entrada" else "🔴"
        if t.tipo == "entrada":
            income_total += t.valor
        else:
            expense_total += t.valor
        lines.append(f"{emoji} {t.data.strftime('%d/%m/%Y')} — {t.descricao}: R$ {t.valor:.2f}")

    balance = income_total - expense_total
    lines.append("")
    lines.append("<b>Resumo</b>")
    lines.append(f"🟢 Entradas: R$ {income_total:.2f}")
    lines.append(f"🔴 Saídas: R$ {expense_total:.2f}")
    lines.append(f"💰 Saldo: R$ {balance:.2f}")

    return "\n".join(lines)
```

---

## T7 — `services/nlp_service.py`: renomear função e variáveis

**Arquivo:** `services/nlp_service.py`

**Antes:**
```python
import json
from datetime import date

from google import genai
from google.genai import types

from models import Transacao
from prompts import TRANSACTION_SCHEMA
from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_text_transference(txt: str) -> list[Transacao]:
    today = date.today().isoformat()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            f'A data de hoje é {today}. O usuário escreveu: "{txt}". '
            f'Responda APENAS com JSON neste formato: {{"e_transacao": true|false, "transacoes": {TRANSACTION_SCHEMA}}}. '
            'Marque "e_transacao" como false se a mensagem não descrever um gasto ou '
            'recebimento (ex: saudação, pergunta, conversa solta). Nesse caso, '
            '"transacoes" deve ser uma lista vazia. '
            "Se não houver data explícita na mensagem, use a data de hoje."
        ),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    dados = json.loads(response.text)

    if not dados.get("e_transacao"):
        return []

    return [Transacao(**item) for item in dados["transacoes"]]
```

**Depois:**
```python
import json
from datetime import date

from google import genai
from google.genai import types

from models import Transacao
from prompts import TRANSACTION_SCHEMA
from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_text_transactions(text: str) -> list[Transacao]:
    today = date.today().isoformat()

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=(
            f'A data de hoje é {today}. O usuário escreveu: "{text}". '
            f'Responda APENAS com JSON neste formato: {{"e_transacao": true|false, "transacoes": {TRANSACTION_SCHEMA}}}. '
            'Marque "e_transacao" como false se a mensagem não descrever um gasto ou '
            'recebimento (ex: saudação, pergunta, conversa solta). Nesse caso, '
            '"transacoes" deve ser uma lista vazia. '
            "Se não houver data explícita na mensagem, use a data de hoje."
        ),
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    response_data = json.loads(response.text)

    if not response_data.get("e_transacao"):
        return []

    return [Transacao(**item) for item in response_data["transacoes"]]
```

---

## T8 — `services/ocr_service.py`: renomear parâmetro e variável

**Arquivo:** `services/ocr_service.py`

**Antes:**
```python
import json

from google import genai
from google.genai import types

from models import Transacao
from prompts import TRANSACTION_SCHEMA
from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_photo_data(caminho_imagem: str) -> list[Transacao]:
    with open(caminho_imagem, "rb") as f:
        file_bytes = f.read()

    if caminho_imagem.endswith(".jpg"):
        mime_type = "image/jpeg"
        prompt = "Extraia as transações desta imagem de extrato bancário. "
    elif caminho_imagem.endswith(".pdf"):
        mime_type = "application/pdf"
        prompt = "Extraia as transações desse pdf de extrato bancário. "
    else:
        raise ValueError(f"Formato não suportado: {caminho_imagem}")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            (prompt + f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"),
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    dados = json.loads(response.text)
    return [Transacao(**item) for item in dados]
```

**Depois:**
```python
import json

from google import genai
from google.genai import types

from models import Transacao
from prompts import TRANSACTION_SCHEMA
from run_polling.config import GEMINI_API_KEY

client = genai.Client(api_key=GEMINI_API_KEY)


async def extract_photo_data(image_path: str) -> list[Transacao]:
    with open(image_path, "rb") as f:
        file_bytes = f.read()

    if image_path.endswith(".jpg"):
        mime_type = "image/jpeg"
        prompt = "Extraia as transações desta imagem de extrato bancário. "
    elif image_path.endswith(".pdf"):
        mime_type = "application/pdf"
        prompt = "Extraia as transações desse pdf de extrato bancário. "
    else:
        raise ValueError(f"Formato não suportado: {image_path}")

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[
            types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            (prompt + f"Responda APENAS com JSON: {TRANSACTION_SCHEMA}"),
        ],
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )

    response_data = json.loads(response.text)
    return [Transacao(**item) for item in response_data]
```

---

## T9 — Handlers: renomear variáveis e atualizar imports

### `handlers/text_handler.py`

**Antes:**
```python
from telegram import Update
from telegram.ext import ContextTypes

from services.message_service import formatter_message, split_message
from services.nlp_service import extract_text_transference
from services.transacao_service import salvar_transacoes


async def get_message(update: Update, context: ContextTypes):
    usuario_id = update.effective_user.id
    txt = update.message.text
    transactions = await extract_text_transference(txt)

    if not transactions:
        await update.message.reply_text(
            "Não foi identificada nenhuma transação nessa mensagem."
            " Tente algo como 'Gastei 30 reais no mercado'"
        )
        return

    await salvar_transacoes(transactions, usuario_id)

    msg = formatter_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
```

**Depois:**
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

    await save_transactions(transactions, user_id)

    msg = format_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
```

### `handlers/photo_handler.py`

**Antes:**
```python
import os

from services.message_service import formatter_message
from services.ocr_service import extract_photo_data
from services.transacao_service import salvar_transacoes


async def get_photo(update, context):
    usuario_id = update.effective_user.id
    photo = update.message.photo[-1]
    file = await photo.get_file()
    path = f"fotos/{photo.file_unique_id}.jpg"
    await update.message.reply_text("...")
    await file.download_to_drive(path)

    try:
        transactions = await extract_photo_data(path)
    finally:
        os.remove(path)

    await salvar_transacoes(transactions, usuario_id)
    mensagem = formatter_message(transactions)
    await update.message.reply_text(mensagem, parse_mode="HTML")
```

**Depois:**
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

### `handlers/pdf_handler.py`

**Antes:**
```python
import os

from telegram import Update

from services.message_service import formatter_message, split_message
from services.ocr_service import extract_photo_data
from services.transacao_service import salvar_transacoes


async def get_pdf(update: Update, context):
    usuario_id = update.effective_user.id
    pdf = update.message.document
    file_pdf = await pdf.get_file()
    path_pdf = f"fotos/{pdf.file_unique_id}.pdf"
    await update.message.reply_text("...")
    await file_pdf.download_to_drive(path_pdf)

    try:
        transactions = await extract_photo_data(path_pdf)
    finally:
        os.remove(path_pdf)

    await salvar_transacoes(transactions, usuario_id)
    msg = formatter_message(transactions)
    for block in split_message(msg):
        await update.message.reply_text(block, parse_mode="HTML")
```

**Depois:**
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

---

## T10 — Smoke test de importação

Com o `venv` ativo, rodar:

```bash
python -c "import main"
```

Deve executar sem erros. Se aparecer `ImportError` ou `ModuleNotFoundError`, corrigir o import antes de concluir.

---

## Regra do Escoteiro — Testes

Não há test runner configurado no projeto. O critério de conclusão é o smoke test do T10. Nenhum teste novo é criado neste TASKS.

---

## Cenários de Teste Manual

| Cenário | Resultado esperado |
|---|---|
| `python -c "import main"` sem erro | Todos os imports resolvidos |
| Enviar mensagem de texto ao bot | Bot responde normalmente |
| Enviar foto de extrato | Bot processa e responde |
| Enviar PDF de extrato | Bot processa e responde |

---

## Fora de Escopo

- Campos do modelo `Transacao` (`descricao`, `valor`, `tipo`, `categoria`)
- Valores de domínio (`"entrada"`, `"saida"`)
- `__tablename__ = "transacoes"`
- Strings ao usuário e prompts ao Gemini
- Configurar test runner
- Renomear a pasta `fotos/`
