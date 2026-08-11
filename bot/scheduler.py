import asyncio
import logging
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import timezone, timedelta
from aiogram import Bot
from sqlalchemy import select
from bot.database import AsyncSessionLocal
from bot.models import User, UserSettings, LearnedWord
from bot.services.gigachat import generate_word

logger = logging.getLogger(__name__)

MOSCOW_TZ = timezone(timedelta(hours=3))
scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)

async def send_daily_word(bot: Bot):
    """Отправляет слово дня всем пользователям."""
    logger.info("Запущена ежедневная рассылка слов")
    async with AsyncSessionLocal() as session:
        users = await session.scalars(select(User))
        user_list = list(users)
        logger.info(f"Найдено {len(user_list)} пользователей для рассылки")
        for user in user_list:
            try:
                settings = await session.scalar(
                    select(UserSettings).where(UserSettings.user_id == user.id)
                )
                difficulty = settings.difficulty if settings else "medium"

                learned = await session.scalars(
                    select(LearnedWord.word).where(LearnedWord.user_id == user.id)
                )
                exclude_list = list(learned)

                word_data = await generate_word(difficulty, exclude_list)

                text = (
                    f"📚 *Слово дня*\n\n"
                    f"*{word_data['word']}*\n"
                    f"_{word_data.get('transcription', '')}_\n\n"
                    f"📖 {word_data['translation']}\n"
                    f"*Пример:* {word_data['example']}"
                )
                await bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="Markdown")
                logger.info(f"Слово дня отправлено пользователю {user.telegram_id}")
                await asyncio.sleep(0.1)
            except Exception as e:
                logger.error(f"Ошибка отправки слова пользователю {user.telegram_id}: {e}")

def start_scheduler(bot: Bot):
    scheduler.add_job(
        send_daily_word,
        trigger=CronTrigger(hour=10, minute=0),
        args=[bot],
        id="morning_word",
    )
    scheduler.add_job(
        send_daily_word,
        trigger=CronTrigger(hour=20, minute=0),
        args=[bot],
        id="evening_word",
    )
    scheduler.start()
    logger.info("Планировщик запущен. Рассылка в 10:00 и 20:00 по МСК.")
