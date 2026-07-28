from run_polling.config import S3_BUCKET_NAME, STORAGE_BACKEND
from services.storage.local_provider import LocalStorageProvider
from services.storage.provider import StorageProvider
from services.storage.s3_provider import S3StorageProvider


def get_storage_provider() -> StorageProvider:
    if STORAGE_BACKEND == "local":
        return LocalStorageProvider()
    if STORAGE_BACKEND == "s3":
        return S3StorageProvider(bucket_name=S3_BUCKET_NAME)
    raise ValueError(f"STORAGE_BACKEND inválido: {STORAGE_BACKEND!r} (esperado 'local' ou 's3')")
