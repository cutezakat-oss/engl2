import json
import random
import logging
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from bot.models import Battle, BattleRound
from bot.services.gigachat import generate_question, GigaChatError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

async def create_battle(session: AsyncSession, player1_id: int, difficulty: str = "medium") -> Battle:
    battle = Battle(
        player1_id=player1_id,
        status="waiting",
        rounds_total=10,
        current_round=0,
        player1_score=0,
        player2_score=0,
        difficulty=difficulty
    )
    session.add(battle)
    await session.commit()
    await session.refresh(battle)
    return battle

async def find_waiting_battle(session: AsyncSession) -> Battle | None:
    stmt = select(Battle).where(Battle.status == "waiting").limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()

async def join_battle(session: AsyncSession, battle: Battle, player2_id: int) -> Battle:
    battle.player2_id = player2_id
    battle.status = "active"
    await session.commit()
    await session.refresh(battle)
    return battle

async def generate_round_question(difficulty: str = "medium") -> dict:
    q_type = random.choice(["word_to_translate", "translate_to_word"])
    question = await generate_question(difficulty, q_type)
    question["question_type"] = q_type
    return question

async def create_rounds_for_battle(session: AsyncSession, battle_id: int, difficulty: str = "medium", rounds_count: int = 10):
    logger.info(f"Создаём {rounds_count} раундов для битвы {battle_id} со сложностью {difficulty}")
    battle = await session.get(Battle, battle_id)
    if not battle:
        logger.error(f"Битва {battle_id} не найдена")
        return

    for i in range(1, rounds_count + 1):
        try:
            question = await generate_round_question(difficulty)
        except GigaChatError as e:
            logger.error(f"Ошибка генерации вопроса для раунда {i}: {e}")
            # Удаляем уже созданные раунды (если они были)
            await session.rollback()
            raise GigaChatError(f"Не удалось сгенерировать вопросы для битвы: {e}") from e

        round_obj = BattleRound(
            battle_id=battle_id,
            round_number=i,
            question_type=question["question_type"],
            word=question["word"],
            correct_answer=question["correct_answer"],
            options=json.dumps(question["options"])
        )
        session.add(round_obj)
        logger.info(f"Добавлен раунд {i} (тип: {question['question_type']})")
    await session.commit()
    logger.info(f"Раунды для битвы {battle_id} сохранены")