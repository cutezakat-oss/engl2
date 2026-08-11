import json
import asyncio
import logging
from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func
from bot.database import AsyncSessionLocal
from bot.models import User, Battle, BattleRound
from bot.services.battle_logic import create_battle, find_waiting_battle, join_battle, create_rounds_for_battle
from bot.states.battle import BattleStates
from bot.keyboards.reply import get_main_keyboard
from bot.services.settings import get_or_create_settings
from bot.services.gigachat import GigaChatError

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

router = Router()

def get_back_keyboard():
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
        ]
    )

def get_question_keyboard(options: list, round_id: int) -> InlineKeyboardMarkup:
    buttons = []
    for idx, opt in enumerate(options):
        buttons.append(
            InlineKeyboardButton(
                text=f"{chr(65+idx)}. {opt}",
                callback_data=f"battle_answer_{round_id}_{idx}"
            )
        )
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[buttons[i:i+2] for i in range(0, len(buttons), 2)]
    )
    return keyboard

@router.message(Command("battle"))
async def cmd_battle(message: types.Message, state: FSMContext):
    await start_battle_search(message, state)

@router.message(lambda message: message.text == "⚔️ Соревнования")
async def text_battle(message: types.Message, state: FSMContext):
    await start_battle_search(message, state)

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

            settings = await get_or_create_settings(user.id, session)
            difficulty = settings.difficulty

            waiting_battle = await find_waiting_battle(session)
            if waiting_battle:
                logger.info(f"Найдена ожидающая битва {waiting_battle.id}, присоединяем игрока {user.id}")
                battle = await join_battle(session, waiting_battle, user.id)
                await state.update_data(battle_id=battle.id)
                await state.set_state(BattleStates.battle_active)

                player1 = await session.get(User, battle.player1_id)
                player1_telegram_id = player1.telegram_id if player1 else None

                await message.answer("⏳ Ожидайте начала битвы... Генерируем вопросы...")
                if player1_telegram_id and player1_telegram_id != user_id:
                    await message.bot.send_message(
                        player1_telegram_id,
                        "⏳ Ожидайте начала битвы... Генерируем вопросы..."
                    )

                try:
                    await create_rounds_for_battle(session, battle.id, difficulty, 10)
                except GigaChatError as e:
                    logger.error(f"Ошибка генерации вопросов: {e}")
                    await session.delete(battle)
                    await session.commit()
                    await message.answer("❌ Не удалось сгенерировать вопросы для битвы. Попробуйте позже.")
                    if player1_telegram_id and player1_telegram_id != user_id:
                        await message.bot.send_message(
                            player1_telegram_id,
                            "❌ Не удалось сгенерировать вопросы для битвы. Попробуйте позже."
                        )
                    await state.clear()
                    return

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
                battle = await create_battle(session, user.id, difficulty)
                await state.update_data(battle_id=battle.id)
                await state.set_state(BattleStates.waiting_for_opponent)
                await message.answer(
                    "⏳ Ищем соперника... Пожалуйста, подождите.\n"
                    "Вы можете отменить поиск командой /cancel_battle"
                )
        except Exception as e:
            logger.error(f"Ошибка в start_battle_search: {e}", exc_info=True)
            await message.answer("❌ Произошла ошибка. Попробуйте позже.")

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

        if round_obj.question_type == "word_to_translate":
            question_text = f"📝 *Переведите слово:*\n{round_obj.word}"
        else:
            question_text = f"📝 *Какое слово означает:*\n{round_obj.correct_answer}"

        options = json.loads(round_obj.options)
        keyboard = get_question_keyboard(options, round_obj.id)

        for player_id in [battle.player1_id, battle.player2_id]:
            player = await session.get(User, player_id)
            if player:
                try:
                    await bot.send_message(
                        player.telegram_id,
                        question_text,
                        parse_mode="Markdown",
                        reply_markup=keyboard
                    )
                    logger.info(f"Вопрос отправлен игроку {player.telegram_id}")
                except Exception as e:
                    logger.error(f"Не удалось отправить вопрос игроку {player.telegram_id}: {e}")

        await state.update_data(round_start_time=asyncio.get_event_loop().time())
        await state.update_data(current_round_id=round_obj.id)

        asyncio.create_task(timeout_round(message_or_callback, state, battle_id, round_obj.id, session))
    except Exception as e:
        logger.error(f"Ошибка в start_round: {e}", exc_info=True)
        await bot.send_message(chat_id, f"❌ Произошла ошибка при запуске раунда. Попробуйте позже.")

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
                        "⏰ Время вышло! Переходим к следующему вопросу."
                    )
                except Exception as e:
                    logger.error(f"Не удалось отправить сообщение о таймауте игроку {player.telegram_id}: {e}")

        await start_round(message_or_callback, state, battle_id, session)
    except Exception as e:
        logger.error(f"Ошибка в timeout_round: {e}", exc_info=True)

@router.callback_query(F.data.startswith("battle_answer_"))
async def handle_battle_answer(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = callback.data.split("_")
    round_id = int(data[2])
    option_index = int(data[3])
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        try:
            round_obj = await session.get(BattleRound, round_id)
            if not round_obj:
                await callback.message.edit_text("❌ Раунд не найден.")
                return

            battle = await session.get(Battle, round_obj.battle_id)
            if not battle or battle.status != "active":
                await callback.message.edit_text("❌ Битва уже завершена.")
                return

            player = await session.scalar(select(User).where(User.telegram_id == user_id))
            if not player:
                await callback.message.edit_text("❌ Вы не зарегистрированы.")
                return

            player_field = None
            if battle.player1_id == player.id:
                player_field = "player1"
            elif battle.player2_id == player.id:
                player_field = "player2"
            else:
                await callback.message.edit_text("❌ Вы не участник этой битвы.")
                return

            if player_field == "player1" and round_obj.player1_answer is not None:
                await callback.message.edit_text("Вы уже ответили на этот вопрос.")
                return
            if player_field == "player2" and round_obj.player2_answer is not None:
                await callback.message.edit_text("Вы уже ответили на этот вопрос.")
                return

            options = json.loads(round_obj.options)
            selected_answer = options[option_index]

            if player_field == "player1":
                round_obj.player1_answer = selected_answer
                round_obj.player1_time = asyncio.get_event_loop().time() - (await state.get_data()).get("round_start_time", 0)
            else:
                round_obj.player2_answer = selected_answer
                round_obj.player2_time = asyncio.get_event_loop().time() - (await state.get_data()).get("round_start_time", 0)

            await session.commit()

            if round_obj.player1_answer is not None and round_obj.player2_answer is not None:
                correct = round_obj.correct_answer
                p1_correct = round_obj.player1_answer == correct
                p2_correct = round_obj.player2_answer == correct

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
                            await callback.bot.send_message(p.telegram_id, result_text, parse_mode="Markdown")
                        except Exception as e:
                            logger.error(f"Не удалось отправить результат игроку {p.telegram_id}: {e}")

                if battle.current_round >= battle.rounds_total:
                    await finish_battle(callback, state, battle, session)
                else:
                    await start_round(callback, state, battle.id, session)
            else:
                await callback.message.edit_text("⏳ Ожидаем ответа соперника...")
        except Exception as e:
            logger.error(f"Ошибка в handle_battle_answer: {e}", exc_info=True)
            await callback.message.edit_text("❌ Произошла ошибка. Попробуйте позже.")

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
            except Exception as e:
                logger.error(f"Не удалось отправить результат игроку {p.telegram_id}: {e}")

    await state.clear()

@router.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_from_battle(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.delete()
    from bot.handlers.menu import show_menu
    await show_menu(callback.message)
