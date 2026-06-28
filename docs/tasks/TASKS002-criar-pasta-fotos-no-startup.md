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

# TASKS002 — Garantir criação da pasta `fotos/` no startup

## Contexto

Os handlers de foto e PDF baixam arquivos para `fotos/{id}.jpg` e `fotos/{id}.pdf` via `download_to_drive()`. Se o diretório `fotos/` não existir, a chamada levanta `FileNotFoundError` silenciosamente antes de qualquer OCR.

Nenhum código atual garante a existência do diretório. A correção é uma linha em `main.py`, no startup, junto ao `init_db()`.

`os.makedirs("fotos", exist_ok=True)` é idempotente — não levanta erro se o diretório já existir.

---

## Progresso

- [x] T1 — Adicionar `os.makedirs` em `main.py`
- [x] T2 — Smoke test de importação

---

## Ordem de Execução

T1 → T2

---

## T1 — Adicionar `os.makedirs` em `main.py`

**Arquivo:** `main.py`

**Antes:**
```python
import asyncio

from telegram.ext import Application, MessageHandler, filters

from handlers.pdf_handler import get_pdf
from handlers.photo_handler import get_photo
from handlers.text_handler import get_message
from run_polling.config import BOT_TOKEN
from database.connection import init_db


def main():
    asyncio.run(init_db())

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, get_message))
    app.add_handler(MessageHandler(filters.PHOTO, get_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, get_pdf))
    print("Bot rodando... aguardando mensagens.")
    app.run_polling()


if __name__ == "__main__":
    main()
```

**Depois:**
```python
import asyncio
import os

from telegram.ext import Application, MessageHandler, filters

from handlers.pdf_handler import get_pdf
from handlers.photo_handler import get_photo
from handlers.text_handler import get_message
from run_polling.config import BOT_TOKEN
from database.connection import init_db


def main():
    asyncio.run(init_db())
    os.makedirs("fotos", exist_ok=True)

    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(MessageHandler(filters.TEXT, get_message))
    app.add_handler(MessageHandler(filters.PHOTO, get_photo))
    app.add_handler(MessageHandler(filters.Document.PDF, get_pdf))
    print("Bot rodando... aguardando mensagens.")
    app.run_polling()


if __name__ == "__main__":
    main()
```

**Critério de aceitação:** `python -c "import main"` executa sem erro.

---

## T2 — Smoke test

```bash
python -c "import main"
```

Sem output = ok.

---

## Regra do Escoteiro — Testes

Sem test runner configurado. Critério de conclusão: smoke test do T2.

---

## Cenários de Teste Manual

| Cenário | Resultado esperado |
|---|---|
| Deletar pasta `fotos/` e rodar `python main.py` | Bot inicia sem erro; pasta `fotos/` recriada |
| Rodar `python main.py` com `fotos/` já existente | Bot inicia normalmente sem erro |

---

## Fora de Escopo

- Limpeza periódica de arquivos antigos em `fotos/`
- Configurar path via variável de ambiente
