from datetime import date, datetime

from models import DEFAULT_CATEGORIA, Transacao
from repository.provider import PendingConfirmation, TransactionSaveResult
from services.message_service import format_message, format_pending_message


def _transacao(descricao="cafe", valor=8.0, tipo="saida", categoria="alimentacao"):
    return Transacao(data=date(2026, 6, 15), descricao=descricao, valor=valor, tipo=tipo, categoria=categoria)


def test_format_message_empty_list_returns_no_transaction_message():
    assert format_message([]) == "Não encontrei nenhuma transação nessa imagem."


def test_format_message_only_nova_sums_totals():
    results = [
        TransactionSaveResult(transacao=_transacao(descricao="salario", valor=1000.0, tipo="entrada"), status="nova"),
        TransactionSaveResult(transacao=_transacao(descricao="mercado", valor=300.0, tipo="saida"), status="nova"),
    ]

    message = format_message(results)

    assert "Entradas: R$ 1000.00" in message
    assert "Saídas: R$ 300.00" in message
    assert "Saldo: R$ 700.00" in message


def test_format_message_duplicata_exata_shows_warning_and_excludes_from_totals():
    results = [TransactionSaveResult(transacao=_transacao(valor=8.0, tipo="saida"), status="duplicata_exata")]

    message = format_message(results)

    assert "⚠️" not in message
    assert "🟡" in message
    assert "aguardando sua confirmação" in message
    assert "Saídas: R$ 0.00" in message


def test_format_message_suspeita_shows_marker_and_excludes_from_totals():
    results = [TransactionSaveResult(transacao=_transacao(valor=8.0, tipo="saida"), status="suspeita")]

    message = format_message(results)

    assert "🟡" in message
    assert "aguardando sua confirmação" in message
    assert "Saídas: R$ 0.00" in message


def test_format_message_categoria_outros_shows_alert_note():
    results = [TransactionSaveResult(transacao=_transacao(categoria=DEFAULT_CATEGORIA), status="nova")]

    message = format_message(results)

    assert "categoria não identificada" in message
    assert DEFAULT_CATEGORIA in message


def test_format_message_categoria_preenchida_does_not_show_alert_note():
    results = [TransactionSaveResult(transacao=_transacao(categoria="alimentacao"), status="nova")]

    message = format_message(results)

    assert "categoria não identificada" not in message


def test_format_message_suspeita_does_not_show_categoria_note():
    results = [
        TransactionSaveResult(transacao=_transacao(categoria=DEFAULT_CATEGORIA), status="suspeita")
    ]

    message = format_message(results)

    assert "aguardando sua confirmação" in message
    assert "categoria não identificada" not in message


def test_format_message_valor_zero_shows_alert_note():
    results = [TransactionSaveResult(transacao=_transacao(valor=0.0), status="nova")]

    message = format_message(results)

    assert "valor não identificado" in message


def test_format_message_valor_diferente_de_zero_does_not_show_alert_note():
    results = [TransactionSaveResult(transacao=_transacao(valor=8.0), status="nova")]

    message = format_message(results)

    assert "valor não identificado" not in message


def test_format_message_categoria_outros_e_valor_zero_combina_as_duas_notas():
    results = [
        TransactionSaveResult(transacao=_transacao(categoria=DEFAULT_CATEGORIA, valor=0.0), status="nova")
    ]

    message = format_message(results)

    assert "categoria não identificada" in message
    assert "valor não identificado" in message


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
    similar_criado_em = datetime(2026, 6, 15, 12, 0, 0)
    pendencia = PendingConfirmation(
        id="abc", transacao=_transacao(), motivo="suspeita",
        criado_em=criado_em, similar_criado_em=similar_criado_em,
    )
    texto = format_pending_message(pendencia)
    assert "pode ter sido sem querer" in texto


def test_format_pending_message_long_interval_uses_neutral_text():
    criado_em = datetime(2026, 6, 15, 18, 0, 0)
    similar_criado_em = datetime(2026, 6, 15, 12, 0, 0)
    pendencia = PendingConfirmation(
        id="abc", transacao=_transacao(), motivo="suspeita",
        criado_em=criado_em, similar_criado_em=similar_criado_em,
    )
    texto = format_pending_message(pendencia)
    assert "Já existe um lançamento parecido registrado antes." in texto
    assert "pode ter sido sem querer" not in texto
