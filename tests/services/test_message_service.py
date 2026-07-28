from datetime import date

from models import Transacao
from repository.provider import TransactionSaveResult
from services.message_service import format_message


def _transacao(descricao="cafe", valor=8.0, tipo="saida"):
    return Transacao(data=date(2026, 6, 15), descricao=descricao, valor=valor, tipo=tipo, categoria="alimentacao")


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

    assert "⚠️" in message
    assert "Saídas: R$ 0.00" in message


def test_format_message_suspeita_shows_marker_and_includes_in_totals():
    results = [TransactionSaveResult(transacao=_transacao(valor=8.0, tipo="saida"), status="suspeita")]

    message = format_message(results)

    assert "🟡" in message
    assert "parece semelhante" in message
    assert "Saídas: R$ 8.00" in message
