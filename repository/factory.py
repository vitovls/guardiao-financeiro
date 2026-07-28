from run_polling.config import DB_BACKEND, DYNAMO_TABLE_NAME
from repository.dynamo_repository import DynamoTransactionRepository
from repository.provider import TransactionRepository
from repository.sqlite_repository import SqliteTransactionRepository


def get_transaction_repository() -> TransactionRepository:
    if DB_BACKEND == "sqlite":
        return SqliteTransactionRepository()
    if DB_BACKEND == "dynamo":
        return DynamoTransactionRepository(table_name=DYNAMO_TABLE_NAME)
    raise ValueError(f"DB_BACKEND inválido: {DB_BACKEND!r} (esperado 'sqlite' ou 'dynamo')")
