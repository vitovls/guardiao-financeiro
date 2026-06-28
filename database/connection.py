from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from database.base import Base

DATABASE_URL="sqlite+aiosqlite:///guardiao.db"

engine = create_async_engine(DATABASE_URL, echo=False)

async_session = async_sessionmaker(engine, expire_on_commit=False)

async def init_db() -> None:
    """Cria as tabelas se ainda não existirem."""
    async with engine.begin() as conn:
      await conn.run_sync(Base.metadata.create_all)