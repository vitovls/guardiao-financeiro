import pytest

from repository.dynamo_repository import DynamoTransactionRepository
from repository.factory import get_transaction_repository
from repository.sqlite_repository import SqliteTransactionRepository


def test_sqlite_repository_selected_when_db_backend_is_sqlite(monkeypatch):
    monkeypatch.setattr("repository.factory.DB_BACKEND", "sqlite")

    repository = get_transaction_repository()

    assert isinstance(repository, SqliteTransactionRepository)


def test_dynamo_repository_selected_when_db_backend_is_dynamo(monkeypatch):
    monkeypatch.setattr("repository.factory.DB_BACKEND", "dynamo")

    repository = get_transaction_repository()

    assert isinstance(repository, DynamoTransactionRepository)


def test_invalid_db_backend_raises_value_error(monkeypatch):
    monkeypatch.setattr("repository.factory.DB_BACKEND", "outro")

    with pytest.raises(ValueError):
        get_transaction_repository()
