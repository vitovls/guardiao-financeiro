import asyncio
import sys
from datetime import date

from repository.config_repository import ConfigRepository
from run_polling.config import DYNAMO_TABLE_NAME


async def seed(user_id: int, nome: str, teto: float, periodo: str, rollover: bool, data_limite: str | None) -> None:
    repo = ConfigRepository(table_name=DYNAMO_TABLE_NAME)
    await repo.save_config(
        telegram_user_id=user_id,
        nome=nome,
        teto=teto,
        periodo=periodo,
        rollover=rollover,
        data_limite=date.fromisoformat(data_limite) if data_limite else None,
    )
    print(f"Configuração '{nome}' gravada para o usuário {user_id} (periodo={periodo}, teto={teto}).")


if __name__ == "__main__":
    # uso: python scripts/seed_config.py <user_id> <nome> <teto> <mensal|unico> [rollover=true|false] [data_limite=YYYY-MM-DD]
    user_id = int(sys.argv[1])
    nome = sys.argv[2]
    teto = float(sys.argv[3])
    periodo = sys.argv[4]
    rollover = len(sys.argv) > 5 and sys.argv[5].lower() == "true"
    data_limite = sys.argv[6] if len(sys.argv) > 6 else None
    asyncio.run(seed(user_id, nome, teto, periodo, rollover, data_limite))
