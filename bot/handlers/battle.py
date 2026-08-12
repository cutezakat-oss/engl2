import json
import asyncio
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func, delete
from bot.database import AsyncSessionLocal
from bot.models import User, Battle, BattleRound, StudyWord
from bot.services.battle_logic import create_battle, find_waiting_battle, join_battle, create_rounds_for_battle
from bot.services.word_levels import get_level_by_elo
from bot.states.battle import BattleStates
from bot.keyboards.reply import get_main_keyboard

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = Router()

# ---------- Вспомогательные клавиатуры ----------
def get_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
        ]
    )

def get_cancel_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="❌ Отменить поиск", callback_data="cancel_search")]
        ]
    )

def get_exit_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🚪 Выйти из боя", callback_data="exit_battle")]
        ]
    )

async def get_queue_count(session) -> int:
    count = await session.scalar(
        select(func.count()).select_from(Battle).where(Battle.status == "waiting")
    )
    return count or 0

async def update_elo(session, winner_id: int, loser_id: int):
    K = 32
    winner = await session.get(User, winner_id)
    loser = await session.get(User, loser_id)
    if not winner or not loser:
        return
    expected_win = 1 / (1 + 10 ** ((loser.elo - winner.elo) / 400))
    expected_lose = 1 - expected_win
    new_winner_elo = round(winner.elo + K * (1 - expected_win))
    new_loser_elo = round(loser.elo + K * (0 - expected_lose))
    winner.elo = new_winner_elo
    loser.elo = new_loser_elo
    winner.wins += 1
    loser.losses += 1
    winner.games_played += 1
    loser.games_played += 1
    await session.commit()

# ---------- Обработчики команд ----------
@router.message(Command("battle"))
async def cmd_battle(message: types.Message, state: FSMContext):
    await start_battle_search(message, state)

@router.message(lambda message: message.text == "⚔️ Соревнования")
async def text_battle(message: types.Message, state: FSMContext):
    await start_battle_search(message, state)

@router.message(Command("cancel_battle"))
@router.message(lambda message: message.text == "❌ Отменить поиск")
async def cancel_battle_search(message: types.Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == BattleStates.waiting_for_opponent:
        data = await state.get_data()
        battle_id = data.get("battle_id")
        if battle_id:
            async with AsyncSessionLocal() as session:
                battle = await session.get(Battle, battle_id)
                if battle and battle.status == "waiting":
                    await session.delete(battle)
                    await session.commit()
        await state.clear()
        await message.answer("❌ Поиск отменён.", reply_markup=get_main_keyboard())
    else:
        await message.answer("У вас нет активного поиска.")

@router.callback_query(lambda c: c.data == "cancel_search")
async def cancel_search_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await cancel_battle_search(callback.message, state)

@router.callback_query(lambda c: c.data == "exit_battle")
async def exit_battle_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if not user:
            await callback.message.edit_text("❌ Вы не зарегистрированы.")
            return

        battle = await session.scalar(
            select(Battle).where(
                ((Battle.player1_id == user.id) | (Battle.player2_id == user.id)),
                Battle.status == "active"
            )
        )
        if not battle:
            await callback.message.edit_text("❌ Нет активной битвы.")
            return

        opponent_id = battle.player2_id if battle.player1_id == user.id else battle.player1_id
        if not opponent_id:
            battle.status = "finished"
            battle.finished_at = func.now()
            await session.commit()
            await callback.message.edit_text("❌ Битва прервана (ошибка соперника).")
            return

        battle.winner_id = opponent_id
        battle.status = "finished"
        battle.finished_at = func.now()
        if battle.player1_id == user.id:
            battle.player2_score = 100
        else:
            battle.player1_score = 100
        await session.commit()
        await session.refresh(battle)

        await update_elo(session, opponent_id, user.id)

        for pid in [battle.player1_id, battle.player2_id]:
            p = await session.get(User, pid)
            if p:
                try:
                    await callback.bot.send_message(
                        p.telegram_id,
                        f"🚪 Игрок {user.first_name} вышел из боя. Победа присуждена сопернику!",
                        reply_markup=get_back_keyboard()
                    )
                except Exception:
                    pass

        await state.clear()
        await callback.message.edit_text("✅ Вы вышли из боя.")

# ---------- Обработчик добавления неправильных слов в список изучения ----------
@router.callback_query(lambda c: c.data.startswith("add_study_all_"))
async def add_study_all_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = callback.data.split("_")
    battle_id = int(data[3])
    player_id = int(data[4])

    async with AsyncSessionLocal() as session:
        battle = await session.get(Battle, battle_id)
        if not battle:
            await callback.message.edit_text("❌ Битва не найдена.")
            return

        user_id = callback.from_user.id
        if user_id != battle.player1_id and user_id != battle.player2_id:
            await callback.message.edit_text("❌ Вы не участник этой битвы.")
            return

        rounds = await session.scalars(
            select(BattleRound).where(BattleRound.battle_id == battle_id)
        )
        wrong_words = []
        for r in rounds:
            if player_id == battle.player1_id:
                answer = r.player1_answer
            else:
                answer = r.player2_answer
            if answer and answer.lower().strip() != r.correct_answer.lower().strip():
                wrong_words.append({"word": r.word, "translation": r.correct_answer})

        user = await session.get(User, user_id)
        if not user:
            await callback.message.edit_text("❌ Пользователь не найден.")
            return

        added_count = 0
        for w in wrong_words:
            existing = await session.scalar(
                select(StudyWord).where(
                    StudyWord.user_id == user.id,
                    StudyWord.word == w["word"]
                )
            )
            if not existing:
                study = StudyWord(user_id=user.id, word=w["word"], translation=w["translation"])
                session.add(study)
                added_count += 1
        await session.commit()

        await callback.message.edit_text(
            f"✅ Добавлено {added_count} слов в список для изучения."
        )

@router.callback_query(lambda c: c.data == "skip_study")
async def skip_study_callback(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text("✅ Пропущено.")

# ---------- Основная логика поиска соперника ----------
async def start_battle_search(message: types.Message, state: FSMContext):
    user_id = message.from_user.id
    logger.info(f"Поиск соперника для пользователя {user_id}")

    async with AsyncSessionLocal() as session:
        try:
            user = await session.scalar(select(User).where(User.telegram_id == user_id))
            if not user:
                await message.answer("❌ Вы не зарегистрированы. Напишите /start.")
                return

            existing_battle = await session.scalar(
                select(Battle).where(
                    ((Battle.player1_id == user.id) | (Battle.player2_id == user.id)),
                    Battle.status.in_(["waiting", "active"])
                )
            )
            if existing_battle:
                await message.answer("⚠️ У вас уже есть активная битва. Дождитесь её завершения.")
                return

            level = get_level_by_elo(user.elo)

            waiting_battle = await find_waiting_battle(session)
            if waiting_battle:
                battle = await join_battle(session, waiting_battle, user.id)
                await state.update_data(battle_id=battle.id)
                await state.set_state(BattleStates.battle_active)

                player1 = await session.get(User, battle.player1_id)
                player1_telegram_id = player1.telegram_id if player1 else None
                level = battle.difficulty

                await message.answer("⏳ Ожидайте начала битвы... Генерируем вопросы...")
                if player1_telegram_id and player1_telegram_id != user_id:
                    await message.bot.send_message(
                        player1_telegram_id,
                        "⏳ Ожидайте начала битвы... Генерируем вопросы..."
                    )

                await create_rounds_for_battle(session, battle.id, level, 10)

                await message.answer("✅ Соперник найден! Битва начинается!")
                if player1_telegram_id and player1_telegram_id != user_id:
                    await message.bot.send_message(
                        player1_telegram_id,
                        "✅ Соперник найден! Битва начинается!"
                    )

                try:
                    logger.info(f"Запускаем первый раунд битвы {battle.id}")
                    await start_round(message, state, battle.id, session)
                except Exception as e:
                    logger.error(f"Ошибка при запуске первого раунда: {e}", exc_info=True)
                    await message.answer(f"❌ Произошла ошибка при запуске битвы. Попробуйте позже.")
            else:
                logger.info(f"Создаём новую битву для игрока {user.id}")
                battle = await create_battle(session, user.id, level)
                await state.update_data(battle_id=battle.id)
                await state.set_state(BattleStates.waiting_for_opponent)
                queue_count = await get_queue_count(session)
                
                await message.answer(
                    f"⏳ Ищем соперника... В очереди сейчас {queue_count} человек.\n"
                    "Вы можете отменить поиск командой /cancel_battle",
                    reply_markup=get_cancel_keyboard()
                )
        except Exception as e:
            logger.error(f"Ошибка в start_battle_search: {e}", exc_info=True)
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")

# ---------- Запуск раунда ----------
async def start_round(message_or_callback, state: FSMContext, battle_id: int, session):
    logger.info(f"start_round вызван для битвы {battle_id}")
    if isinstance(message_or_callback, types.Message):
        bot = message_or_callback.bot
        chat_id = message_or_callback.chat.id
    else:
        bot = message_or_callback.bot
        chat_id = message_or_callback.message.chat.id

    try:
        battle = await session.get(Battle, battle_id)
        if not battle or battle.status != "active":
            await bot.send_message(chat_id, "❌ Битва уже завершена или не найдена.")
            return

        if battle.current_round >= battle.rounds_total:
            await finish_battle(message_or_callback, state, battle, session)
            return

        round_obj = await session.scalar(
            select(BattleRound).where(
                BattleRound.battle_id == battle_id,
                BattleRound.round_number == battle.current_round + 1
            )
        )
        if not round_obj:
            logger.error(f"Раунд не найден для битвы {battle_id}, текущий раунд {battle.current_round}")
            await bot.send_message(chat_id, "❌ Ошибка: раунд не найден.")
            return

        logger.info(f"Отправляем вопрос раунда {round_obj.round_number} для битвы {battle_id}")

        question_text = f"📝 *Вопрос {round_obj.round_number}/{battle.rounds_total}*\n\nПереведите слово:\n*{round_obj.word}*"

        for player_id in [battle.player1_id, battle.player2_id]:
            player = await session.get(User, player_id)
            if player:
                try:
                    await bot.send_message(
                        player.telegram_id,
                        question_text,
                        parse_mode="Markdown",
                        reply_markup=get_exit_keyboard()
                    )
                    logger.info(f"Вопрос отправлен игроку {player.telegram_id}")
                except Exception as e:
                    logger.error(f"Не удалось отправить вопрос игроку {player.telegram_id}: {e}")

        await state.update_data(current_round_id=round_obj.id)
        await state.update_data(round_start_time=asyncio.get_event_loop().time())

        asyncio.create_task(timeout_round(message_or_callback, state, battle_id, round_obj.id, session))
    except Exception as e:
        logger.error(f"Ошибка в start_round: {e}", exc_info=True)
        await bot.send_message(chat_id, f"❌ Произошла ошибка при запуске раунда. Попробуйте позже.")

# ---------- Таймаут раунда ----------
async def timeout_round(message_or_callback, state: FSMContext, battle_id: int, round_id: int, session):
    await asyncio.sleep(10)
    logger.info(f"Таймаут для раунда {round_id} битвы {battle_id}")
    if isinstance(message_or_callback, types.Message):
        bot = message_or_callback.bot
    else:
        bot = message_or_callback.bot

    try:
        round_obj = await session.get(BattleRound, round_id)
        if not round_obj:
            return
        if round_obj.player1_answer is not None and round_obj.player2_answer is not None:
            return
        battle = await session.get(Battle, battle_id)
        if not battle or battle.status != "active":
            return

        if round_obj.player1_answer is None and round_obj.player2_answer is not None:
            battle.player2_score += 1
        elif round_obj.player2_answer is None and round_obj.player1_answer is not None:
            battle.player1_score += 1
        else:
            pass

        battle.current_round += 1
        await session.commit()

        for player_id in [battle.player1_id, battle.player2_id]:
            player = await session.get(User, player_id)
            if player:
                try:
                    await bot.send_message(
                        player.telegram_id,
                        "⏰ Время вышло! Переходим к следующему вопросу.",
                        reply_markup=get_exit_keyboard()
                    )
                except Exception:
                    pass

        await start_round(message_or_callback, state, battle_id, session)
    except Exception as e:
        logger.error(f"Ошибка в timeout_round: {e}", exc_info=True)

# ---------- Обработчик текстовых ответов ----------
@router.message()
async def handle_answer(message: types.Message, state: FSMContext):
    if message.text.startswith('/'):
        return

    user_id = message.from_user.id
    text = message.text.strip()
    if not text:
        return

    async with AsyncSessionLocal() as session:
        try:
            user = await session.scalar(select(User).where(User.telegram_id == user_id))
            if not user:
                return

            battle = await session.scalar(
                select(Battle).where(
                    ((Battle.player1_id == user.id) | (Battle.player2_id == user.id)),
                    Battle.status == "active"
                )
            )
            if not battle:
                return

            round_obj = await session.scalar(
                select(BattleRound).where(
                    BattleRound.battle_id == battle.id,
                    BattleRound.round_number == battle.current_round + 1
                )
            )
            if not round_obj:
                return

            if battle.player1_id == user.id and round_obj.player1_answer is not None:
                await message.answer("Вы уже ответили на этот вопрос.")
                return
            if battle.player2_id == user.id and round_obj.player2_answer is not None:
                await message.answer("Вы уже ответили на этот вопрос.")
                return

            if battle.player1_id == user.id:
                round_obj.player1_answer = text
                round_obj.player1_time = asyncio.get_event_loop().time() - (await state.get_data()).get("round_start_time", 0)
            elif battle.player2_id == user.id:
                round_obj.player2_answer = text
                round_obj.player2_time = asyncio.get_event_loop().time() - (await state.get_data()).get("round_start_time", 0)
            else:
                return

            await session.commit()

            if round_obj.player1_answer is not None and round_obj.player2_answer is not None:
                correct = round_obj.correct_answer.lower().strip()
                p1_correct = round_obj.player1_answer.lower().strip() == correct
                p2_correct = round_obj.player2_answer.lower().strip() == correct

                if p1_correct and not p2_correct:
                    round_obj.winner_id = battle.player1_id
                    battle.player1_score += 1
                elif p2_correct and not p1_correct:
                    round_obj.winner_id = battle.player2_id
                    battle.player2_score += 1
                elif p1_correct and p2_correct:
                    if round_obj.player1_time < round_obj.player2_time:
                        round_obj.winner_id = battle.player1_id
                        battle.player1_score += 1
                    else:
                        round_obj.winner_id = battle.player2_id
                        battle.player2_score += 1
                else:
                    pass

                battle.current_round += 1
                await session.commit()

                result_text = f"🏆 *Результат раунда {round_obj.round_number}*\n"
                result_text += f"Игрок1: {'✅' if p1_correct else '❌'} ({round_obj.player1_time:.1f}с)\n"
                result_text += f"Игрок2: {'✅' if p2_correct else '❌'} ({round_obj.player2_time:.1f}с)\n"
                if round_obj.winner_id:
                    winner = await session.get(User, round_obj.winner_id)
                    result_text += f"Победитель раунда: {winner.first_name} 🎉"
                else:
                    result_text += "Ничья!"

                for pid in [battle.player1_id, battle.player2_id]:
                    p = await session.get(User, pid)
                    if p:
                        try:
                            await message.bot.send_message(p.telegram_id, result_text, parse_mode="Markdown")
                        except Exception:
                            pass

                if battle.current_round >= battle.rounds_total:
                    await finish_battle(message, state, battle, session)
                else:
                    await start_round(message, state, battle.id, session)
            else:
                await message.answer("⏳ Ожидаем ответа соперника...")
        except Exception as e:
            logger.error(f"Ошибка в handle_answer: {e}", exc_info=True)
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")

# ---------- Завершение битвы и отправка предложения изучить слова ----------
async def finish_battle(message_or_callback, state: FSMContext, battle: Battle, session):
    battle.status = "finished"
    battle.finished_at = func.now()
    if battle.player1_score > battle.player2_score:
        battle.winner_id = battle.player1_id
    elif battle.player2_score > battle.player1_score:
        battle.winner_id = battle.player2_id
    else:
        battle.winner_id = None

    await session.commit()
    await session.refresh(battle)

    if battle.winner_id:
        loser_id = battle.player2_id if battle.winner_id == battle.player1_id else battle.player1_id
        await update_elo(session, battle.winner_id, loser_id)

    result_text = (
        f"🏁 *Битва завершена!*\n\n"
        f"Игрок1: {battle.player1_score} очков\n"
        f"Игрок2: {battle.player2_score} очков\n"
    )
    if battle.winner_id:
        winner = await session.get(User, battle.winner_id)
        result_text += f"🏆 Победитель: {winner.first_name}!"
    else:
        result_text += "🤝 Ничья!"

    if isinstance(message_or_callback, types.Message):
        bot = message_or_callback.bot
    else:
        bot = message_or_callback.bot

    for pid in [battle.player1_id, battle.player2_id]:
        p = await session.get(User, pid)
        if p:
            try:
                await bot.send_message(
                    p.telegram_id,
                    result_text,
                    parse_mode="Markdown",
                    reply_markup=get_back_keyboard()
                )
            except Exception:
                pass

    # -------- Сбор неправильных слов и предложение изучить --------
    rounds = await session.scalars(
        select(BattleRound).where(BattleRound.battle_id == battle.id)
    )
    rounds_list = list(rounds)

    for player_id in [battle.player1_id, battle.player2_id]:
        wrong_words = []
        for r in rounds_list:
            if player_id == battle.player1_id:
                answer = r.player1_answer
            else:
                answer = r.player2_answer
            if answer and answer.lower().strip() != r.correct_answer.lower().strip():
                wrong_words.append({"word": r.word, "translation": r.correct_answer})
        
        if wrong_words:
            player = await session.get(User, player_id)
            if player:
                text = "📚 *Слова, которые вы не угадали:*\n\n"
                for i, w in enumerate(wrong_words, 1):
                    text += f"{i}. *{w['word']}* — {w['translation']}\n"
                text += "\nХотите добавить их в список для изучения?"
                
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(text="✅ Добавить все", callback_data=f"add_study_all_{battle.id}_{player_id}")],
                        [InlineKeyboardButton(text="❌ Пропустить", callback_data="skip_study")]
                    ]
                )
                try:
                    await bot.send_message(
                        player.telegram_id,
                        text,
                        parse_mode="Markdown",
                        reply_markup=keyboard
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить предложение изучения игроку {player.telegram_id}: {e}")

    await state.clear()

# ---------- Кнопка "Назад" ----------
@router.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_from_battle(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.delete()
    from bot.handlers.menu import show_menu
    await show_menu(callback.message)
