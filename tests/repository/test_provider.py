from datetime import date, datetime

import pytest
from pydantic import ValidationError

from models import Transacao
from repository.provider import (
    ConfigItem,
    PendingConfirmation,
    TransactionRepository,
    TransactionSaveResult,
)


class _ConcreteRepository(TransactionRepository):
    async def save_transactions(self, transactions, telegram_user_id):
        return []

    async def find_by_user(self, telegram_user_id):
        return []

    async def get_totals_by_period(self, telegram_user_id, start, end):
        return {}


def test_concrete_subclass_can_be_instantiated():
    repository = _ConcreteRepository()
    assert isinstance(repository, TransactionRepository)


def test_abstract_class_cannot_be_instantiated_directly():
    with pytest.raises(TypeError):
        TransactionRepository()


def _transacao():
    return Transacao(data=date(2026, 1, 1), descricao="cafe", valor=8.0, tipo="saida", categoria="alimentacao")


def test_transaction_save_result_accepts_expected_fields():
    result = TransactionSaveResult(transacao=_transacao(), status="nova")
    assert result.status == "nova"
    assert result.similares == []


def test_transaction_save_result_rejects_status_outside_literal():
    with pytest.raises(ValidationError):
        TransactionSaveResult(transacao=_transacao(), status="invalido")


def test_config_item_accepts_expected_fields():
    now = datetime(2026, 1, 1, 12, 0, 0)
    item = ConfigItem(nome="lazer", teto=300.0, periodo="mensal", created_at=now, updated_at=now)
    assert item.periodo == "mensal"
    assert item.rollover is False
    assert item.data_limite is None


def test_config_item_rejects_periodo_outside_literal():
    now = datetime(2026, 1, 1, 12, 0, 0)
    with pytest.raises(ValidationError):
        ConfigItem(nome="lazer", teto=300.0, periodo="invalido", created_at=now, updated_at=now)


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
