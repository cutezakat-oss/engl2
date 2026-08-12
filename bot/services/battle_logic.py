import json
import random
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.models import Battle, BattleRound
from bot.services.word_levels import WORDS_BY_LEVEL, get_level_by_elo

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

async def create_battle(session: AsyncSession, player1_id: int, level: str = "A1") -> Battle:
    battle = Battle(
        player1_id=player1_id,
        status="waiting",
        rounds_total=10,
        current_round=0,
        player1_score=0,
        player2_score=0,
        difficulty=level  # теперь это уровень (A1, A2, ...)
    )
    session.add(battle)
    await session.commit()
    await session.refresh(battle)
    return battle

async def find_waiting_battle(session: AsyncSession, level: str) -> Battle | None:
    """Ищет ожидающую битву с таким же уровнем."""
    stmt = select(Battle).where(
        Battle.status == "waiting",
        Battle.difficulty == level
    ).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def join_battle(session: AsyncSession, battle: Battle, player2_id: int) -> Battle:
    battle.player2_id = player2_id
    battle.status = "active"
    await session.commit()
    await session.refresh(battle)
    return battle

async def get_word_for_level(level: str, used_words: list) -> tuple:
    words = WORDS_BY_LEVEL.get(level, WORDS_BY_LEVEL["A1"])
    available = [w for w in words if w[0] not in used_words]
    if not available:
        available = words
    return random.choice(available)

async def create_rounds_for_battle(session: AsyncSession, battle_id: int, level: str, rounds_count: int = 10):
    logger.info(f"Создаём {rounds_count} раундов для битвы {battle_id} уровня {level}")
    battle = await session.get(Battle, battle_id)
    if not battle:
        logger.error(f"Битва {battle_id} не найдена")
        return

    used_words = []
    for i in range(1, rounds_count + 1):
        word_en, word_ru = await get_word_for_level(level, used_words)
        used_words.append(word_en)
        round_obj = BattleRound(
            battle_id=battle_id,
            round_number=i,
            question_type="text_input",
            word=word_en,
            correct_answer=word_ru,
            options=""
        )
        session.add(round_obj)
        logger.info(f"Добавлен раунд {i}: {word_en} -> {word_ru}")
    await session.commit()
    logger.info(f"Раунды для битвы {battle_id} сохранены")
