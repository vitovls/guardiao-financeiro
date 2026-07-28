from unittest.mock import AsyncMock, Mock

import handlers.text_handler as text_handler


def _build_update(text: str = "gastei 30 no mercado"):
    update = Mock()
    update.effective_user.id = 42
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


async def test_happy_path_saves_transactions_and_replies_with_formatted_message(monkeypatch):
    update = _build_update()
    context = Mock()

    extract_text_transactions = AsyncMock(return_value=["transacao-fake"])
    monkeypatch.setattr(text_handler, "extract_text_transactions", extract_text_transactions)
    save_transactions = AsyncMock(return_value=["resultado-fake"])
    monkeypatch.setattr(text_handler, "save_transactions", save_transactions)
    format_message = Mock(return_value="mensagem formatada")
    monkeypatch.setattr(text_handler, "format_message", format_message)

    await text_handler.get_message(update, context)

    extract_text_transactions.assert_awaited_once_with("gastei 30 no mercado")
    save_transactions.assert_awaited_once_with(["transacao-fake"], 42)
    format_message.assert_called_once_with(["resultado-fake"])
    update.message.reply_text.assert_any_call("mensagem formatada", parse_mode="HTML")


async def test_no_transactions_identified_replies_and_does_not_save(monkeypatch):
    update = _build_update()
    context = Mock()

    extract_text_transactions = AsyncMock(return_value=[])
    monkeypatch.setattr(text_handler, "extract_text_transactions", extract_text_transactions)
    save_transactions = AsyncMock()
    monkeypatch.setattr(text_handler, "save_transactions", save_transactions)

    await text_handler.get_message(update, context)

    save_transactions.assert_not_awaited()
    update.message.reply_text.assert_awaited_once()
    reply_text = update.message.reply_text.call_args.args[0]
    assert "não foi identificada" in reply_text.lower()
