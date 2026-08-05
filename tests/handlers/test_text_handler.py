from datetime import date
from unittest.mock import AsyncMock, Mock

import handlers.text_handler as text_handler
from services.llm.provider import InterpretacaoTexto


def _build_update(text: str = "gastei 30 no mercado"):
    update = Mock()
    update.effective_user.id = 42
    update.update_id = 1
    update.message.text = text
    update.message.reply_text = AsyncMock()
    return update


async def test_happy_path_saves_transactions_and_replies_with_formatted_message(monkeypatch):
    update = _build_update()
    context = Mock()

    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=True))
    interpret_text = AsyncMock(
        return_value=InterpretacaoTexto.model_construct(intencao="transacao", transacoes=["transacao-fake"])
    )
    monkeypatch.setattr(text_handler, "interpret_text", interpret_text)
    resultado_fake = Mock(pendencia=None)
    save_transactions = AsyncMock(return_value=[resultado_fake])
    monkeypatch.setattr(text_handler, "save_transactions", save_transactions)
    format_message = Mock(return_value="mensagem formatada")
    monkeypatch.setattr(text_handler, "format_message", format_message)

    await text_handler.get_message(update, context)

    interpret_text.assert_awaited_once_with("gastei 30 no mercado")
    save_transactions.assert_awaited_once_with(["transacao-fake"], 42)
    format_message.assert_called_once_with([resultado_fake])
    update.message.reply_text.assert_any_call("mensagem formatada", parse_mode="HTML")


async def test_transacao_intent_sem_transacoes_replies_fallback_and_does_not_save(monkeypatch):
    update = _build_update()
    context = Mock()

    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=True))
    interpret_text = AsyncMock(return_value=InterpretacaoTexto(intencao="transacao", transacoes=[]))
    monkeypatch.setattr(text_handler, "interpret_text", interpret_text)
    save_transactions = AsyncMock()
    monkeypatch.setattr(text_handler, "save_transactions", save_transactions)
    format_no_intent_message = Mock(return_value="texto fallback")
    monkeypatch.setattr(text_handler, "format_no_intent_message", format_no_intent_message)

    await text_handler.get_message(update, context)

    save_transactions.assert_not_awaited()
    update.message.reply_text.assert_awaited_once_with("texto fallback")


async def test_nenhuma_intent_replies_fallback(monkeypatch):
    update = _build_update()
    context = Mock()

    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=True))
    interpret_text = AsyncMock(return_value=InterpretacaoTexto(intencao="nenhuma"))
    monkeypatch.setattr(text_handler, "interpret_text", interpret_text)
    save_transactions = AsyncMock()
    monkeypatch.setattr(text_handler, "save_transactions", save_transactions)
    format_no_intent_message = Mock(return_value="texto fallback")
    monkeypatch.setattr(text_handler, "format_no_intent_message", format_no_intent_message)

    await text_handler.get_message(update, context)

    save_transactions.assert_not_awaited()
    update.message.reply_text.assert_awaited_once_with("texto fallback")


async def test_already_processed_update_skips_extraction(monkeypatch):
    update = _build_update()
    update.update_id = 999
    context = Mock()
    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=False))
    interpret_text = AsyncMock()
    monkeypatch.setattr(text_handler, "interpret_text", interpret_text)

    await text_handler.get_message(update, context)

    interpret_text.assert_not_awaited()
    update.message.reply_text.assert_not_awaited()


async def test_pending_result_sends_extra_message_with_keyboard(monkeypatch):
    update = _build_update()
    update.update_id = 1
    context = Mock()
    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=True))
    monkeypatch.setattr(
        text_handler,
        "interpret_text",
        AsyncMock(return_value=InterpretacaoTexto.model_construct(intencao="transacao", transacoes=["transacao-fake"])),
    )
    pendencia_fake = Mock(id="abc123")
    resultado_fake = Mock(pendencia=pendencia_fake)
    monkeypatch.setattr(text_handler, "save_transactions", AsyncMock(return_value=[resultado_fake]))
    monkeypatch.setattr(text_handler, "format_message", Mock(return_value="resumo"))
    monkeypatch.setattr(text_handler, "format_pending_message", Mock(return_value="texto pendencia"))

    await text_handler.get_message(update, context)

    calls = update.message.reply_text.call_args_list
    assert any(call.args[0] == "texto pendencia" for call in calls)


async def test_consulta_sem_periodo_pede_periodo(monkeypatch):
    update = _build_update("quanto eu já gastei no total?")
    context = Mock()

    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=True))
    monkeypatch.setattr(
        text_handler,
        "interpret_text",
        AsyncMock(
            return_value=InterpretacaoTexto(intencao="consulta", periodo_inicio=None, periodo_fim=None)
        ),
    )
    get_totals = AsyncMock()
    monkeypatch.setattr(text_handler, "get_totals", get_totals)
    format_missing_period_message = Mock(return_value="qual período?")
    monkeypatch.setattr(text_handler, "format_missing_period_message", format_missing_period_message)

    await text_handler.get_message(update, context)

    get_totals.assert_not_awaited()
    update.message.reply_text.assert_awaited_once_with("qual período?")


async def test_consulta_com_periodo_chama_get_totals_e_formata(monkeypatch):
    update = _build_update("quanto gastei em julho?")
    context = Mock()

    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=True))
    monkeypatch.setattr(
        text_handler,
        "interpret_text",
        AsyncMock(
            return_value=InterpretacaoTexto(
                intencao="consulta",
                periodo_inicio=date(2026, 7, 1),
                periodo_fim=date(2026, 7, 31),
                categoria=None,
            )
        ),
    )
    get_totals = AsyncMock(return_value={"entradas": 0.0, "saidas": 100.0})
    monkeypatch.setattr(text_handler, "get_totals", get_totals)
    format_query_message = Mock(return_value="resumo consulta")
    monkeypatch.setattr(text_handler, "format_query_message", format_query_message)

    await text_handler.get_message(update, context)

    get_totals.assert_awaited_once_with(42, date(2026, 7, 1), date(2026, 7, 31), None)
    format_query_message.assert_called_once_with(
        date(2026, 7, 1), date(2026, 7, 31), None, {"entradas": 0.0, "saidas": 100.0}
    )
    update.message.reply_text.assert_awaited_once_with("resumo consulta")


async def test_consulta_com_categoria_repassa_categoria(monkeypatch):
    update = _build_update("quanto gastei em mercado em julho?")
    context = Mock()

    monkeypatch.setattr(text_handler, "claim_update", AsyncMock(return_value=True))
    monkeypatch.setattr(
        text_handler,
        "interpret_text",
        AsyncMock(
            return_value=InterpretacaoTexto(
                intencao="consulta",
                periodo_inicio=date(2026, 7, 1),
                periodo_fim=date(2026, 7, 31),
                categoria="mercado",
            )
        ),
    )
    get_totals = AsyncMock(return_value={"entradas": 0.0, "saidas": 320.0})
    monkeypatch.setattr(text_handler, "get_totals", get_totals)
    monkeypatch.setattr(text_handler, "format_query_message", Mock(return_value="resumo consulta"))

    await text_handler.get_message(update, context)

    get_totals.assert_awaited_once_with(42, date(2026, 7, 1), date(2026, 7, 31), "mercado")
