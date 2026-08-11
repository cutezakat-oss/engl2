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

# Устанавливаем московское время (UTC+3)
MOSCOW_TZ = timezone(timedelta(hours=3))

scheduler = AsyncIOScheduler(timezone=MOSCOW_TZ)

async def send_daily_word(bot: Bot):
    """Отправляет слово дня всем пользователям."""
    async with AsyncSessionLocal() as session:
        users = await session.scalars(select(User))
        for user in users:
            # Получаем настройки сложности
            settings = await session.scalar(
                select(UserSettings).where(UserSettings.user_id == user.id)
            )
            difficulty = settings.difficulty if settings else "medium"
            
            # Получаем выученные слова
            learned = await session.scalars(
                select(LearnedWord.word).where(LearnedWord.user_id == user.id)
            )
            exclude_list = list(learned)
            
            # Генерируем слово
            word_data = await generate_word(difficulty, exclude_list)
            
            # Формируем сообщение с транскрипцией
            text = (
                f"📚 *Слово дня*\n\n"
                f"*{word_data['word']}*\n"
                f"_{word_data.get('transcription', '')}_\n\n"
                f"📖 {word_data['translation']}\n"
                f"*Пример:* {word_data['example']}"
            )
            # Отправляем
            try:
                await bot.send_message(chat_id=user.telegram_id, text=text, parse_mode="Markdown")
            except Exception as e:
                logger.error(f"Не удалось отправить слово пользователю {user.telegram_id}: {e}")
            await asyncio.sleep(0.1)  # задержка, чтобы не превысить лимиты

def start_scheduler(bot: Bot):
    """Запускает планировщик для рассылки в 10:00 и 20:00 МСК."""
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