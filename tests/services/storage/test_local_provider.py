import os

from services.storage.local_provider import LocalStorageProvider


async def test_upload_writes_bytes_to_disk_under_files_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = LocalStorageProvider()

    key = await provider.upload(user_id=1, filename="recibo.jpg", file_bytes=b"fake-bytes")

    assert os.path.exists(key)
    with open(key, "rb") as f:
        assert f.read() == b"fake-bytes"


async def test_delete_removes_file_created_by_upload(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = LocalStorageProvider()
    key = await provider.upload(user_id=1, filename="recibo.jpg", file_bytes=b"fake-bytes")

    await provider.delete(key)

    assert not os.path.exists(key)


async def test_delete_with_nonexistent_key_does_not_raise(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    provider = LocalStorageProvider()

    await provider.delete("files/nao-existe.jpg")
