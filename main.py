import asyncio
from aiogram import Bot, Dispatcher
from bot.config import BOT_TOKEN
from bot.database import init_db, AsyncSessionLocal
from bot.handlers.start import router as start_router
from bot.handlers.menu import router as menu_router
from bot.handlers.translate import router as translate_router
from bot.handlers.battle import router as battle_router
from bot.handlers.reference import router as reference_router
from bot.scheduler import start_scheduler
from bot.models import Battle
from sqlalchemy import delete

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

dp.include_router(start_router)
dp.include_router(menu_router)
dp.include_router(translate_router)
dp.include_router(battle_router)
dp.include_router(reference_router)

async def clear_stale_battles():
    async with AsyncSessionLocal() as session:
        await session.execute(
            delete(Battle).where(Battle.status.in_(["waiting", "active"]))
        )
        await session.commit()
        print("🧹 Очищены незавершённые битвы.")

async def main():
    await init_db()
    await clear_stale_battles()
    print("Бот запущен!")
    start_scheduler(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
