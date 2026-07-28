import time

import boto3

from services.storage.provider import StorageProvider, StorageProviderError


class S3StorageProvider(StorageProvider):
    def __init__(self, bucket_name: str, client=None):
        self._bucket_name = bucket_name
        self._client = client or boto3.client("s3")

    async def upload(self, user_id: int, filename: str, file_bytes: bytes) -> str:
        key = f"{user_id}/files/{int(time.time())}-{filename}"
        try:
            self._client.put_object(Bucket=self._bucket_name, Key=key, Body=file_bytes)
        except Exception as exc:
            raise StorageProviderError(f"falha ao enviar arquivo para S3: {exc}") from exc
        return key

    async def delete(self, key: str) -> None:
        self._client.delete_object(Bucket=self._bucket_name, Key=key)
