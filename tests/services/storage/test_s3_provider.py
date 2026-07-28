from unittest.mock import Mock

import pytest

from services.storage.provider import StorageProviderError
from services.storage.s3_provider import S3StorageProvider


async def test_upload_calls_put_object_with_bucket_key_and_body_and_returns_key():
    client = Mock()
    provider = S3StorageProvider(bucket_name="meu-bucket", client=client)

    key = await provider.upload(user_id=42, filename="recibo.jpg", file_bytes=b"fake-bytes")

    call_kwargs = client.put_object.call_args.kwargs
    assert call_kwargs["Bucket"] == "meu-bucket"
    assert "42" in call_kwargs["Key"]
    assert "recibo.jpg" in call_kwargs["Key"]
    assert call_kwargs["Body"] == b"fake-bytes"
    assert call_kwargs["Key"] == key


async def test_upload_wraps_client_exception_in_storage_provider_error():
    client = Mock()
    client.put_object.side_effect = RuntimeError("falha de rede")
    provider = S3StorageProvider(bucket_name="meu-bucket", client=client)

    with pytest.raises(StorageProviderError):
        await provider.upload(user_id=42, filename="recibo.jpg", file_bytes=b"fake-bytes")


async def test_delete_calls_delete_object_with_bucket_and_key():
    client = Mock()
    provider = S3StorageProvider(bucket_name="meu-bucket", client=client)

    await provider.delete("42/files/123-recibo.jpg")

    client.delete_object.assert_called_once_with(Bucket="meu-bucket", Key="42/files/123-recibo.jpg")
