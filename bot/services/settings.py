from sqlalchemy import select
from bot.models import UserSettings
from bot.database import AsyncSessionLocal

async def get_or_create_settings(user_id: int, session):
    """Получает настройки пользователя или создаёт их со значением по умолчанию."""
    settings = await session.scalar(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    if not settings:
        settings = UserSettings(user_id=user_id, difficulty="medium")
        session.add(settings)
        await session.commit()
    return settings