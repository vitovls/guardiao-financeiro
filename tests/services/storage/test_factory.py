import pytest

from services.storage.factory import get_storage_provider
from services.storage.local_provider import LocalStorageProvider
from services.storage.s3_provider import S3StorageProvider


def test_local_storage_backend_selects_local_provider(monkeypatch):
    monkeypatch.setattr("services.storage.factory.STORAGE_BACKEND", "local")

    provider = get_storage_provider()

    assert isinstance(provider, LocalStorageProvider)


def test_s3_storage_backend_selects_s3_provider(monkeypatch):
    monkeypatch.setattr("services.storage.factory.STORAGE_BACKEND", "s3")

    provider = get_storage_provider()

    assert isinstance(provider, S3StorageProvider)


def test_invalid_storage_backend_raises_value_error(monkeypatch):
    monkeypatch.setattr("services.storage.factory.STORAGE_BACKEND", "outro")

    with pytest.raises(ValueError):
        get_storage_provider()
