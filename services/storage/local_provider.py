import os
import time

from services.storage.provider import StorageProvider

_BASE_DIR = "files"


class LocalStorageProvider(StorageProvider):
    async def upload(self, user_id: int, filename: str, file_bytes: bytes) -> str:
        os.makedirs(_BASE_DIR, exist_ok=True)
        key = f"{_BASE_DIR}/{user_id}-{int(time.time())}-{filename}"
        with open(key, "wb") as f:
            f.write(file_bytes)
        return key

    async def delete(self, key: str) -> None:
        if os.path.exists(key):
            os.remove(key)
