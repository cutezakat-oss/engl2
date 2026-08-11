from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from bot.config import DATABASE_URL
from bot.models import Base

engine = create_async_engine(DATABASE_URL, echo=True)
AsyncSessionLocal = async_sessionmaker(
    engine,
    expire_on_commit=False  # <-- ЭТО ГЛАВНОЕ ИЗМЕНЕНИЕ
)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)