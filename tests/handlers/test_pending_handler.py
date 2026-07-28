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
