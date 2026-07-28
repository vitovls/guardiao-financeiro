import asyncio

from database.connection import async_session
from database.entities.transaction import TransactionEntity
from models import Transacao
from repository.dynamo_repository import DynamoTransactionRepository
from run_polling.config import DYNAMO_TABLE_NAME
from sqlalchemy import select


async def migrate() -> None:
    dynamo_repo = DynamoTransactionRepository(table_name=DYNAMO_TABLE_NAME)
    read_count = 0
    written_count = 0

    async with async_session() as session:
        result = await session.execute(select(TransactionEntity))
        entities = result.scalars().all()

    dropped = []
    for e in entities:
        read_count += 1
        t = Transacao(data=e.data, descricao=e.descricao, valor=e.valor, tipo=e.tipo, categoria=e.categoria)
        results = await dynamo_repo.save_transactions([t], e.telegram_user_id)
        if results[0].status != "duplicata_exata":
            written_count += 1
        else:
            dropped.append(t)

    print(f"Linhas lidas do SQLite: {read_count}")
    print(f"Items gravados no DynamoDB: {written_count}")
    if dropped:
        print(f"Diferença: {len(dropped)} linha(s) já existiam no DynamoDB (duplicata_exata, ignoradas):")
        for t in dropped:
            print(f"  - {t.data.isoformat()} | {t.tipo} | R$ {t.valor:.2f} | {t.descricao}")


if __name__ == "__main__":
    asyncio.run(migrate())
