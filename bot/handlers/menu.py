from aiogram import Router, types
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select, func, delete
from bot.keyboards.reply import get_main_keyboard
from bot.database import AsyncSessionLocal
from bot.models import User, UserSettings, LearnedWord, StudyWord
from bot.services.gigachat import generate_word
from bot.handlers.battle import start_battle_search

router = Router()

def get_back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
        ]
    )

def get_word_keyboard(word: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Выучил", callback_data=f"learn_{word}"),
                InlineKeyboardButton(text="⏭ Еще слово", callback_data="next_word"),
            ],
            [
                InlineKeyboardButton(text="⚙️ Настройки", callback_data="settings"),
                InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"),
            ]
        ]
    )

async def get_or_create_settings(user_id: int, session) -> UserSettings:
    settings = await session.scalar(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    if not settings:
        settings = UserSettings(user_id=user_id, difficulty="medium")
        session.add(settings)
        await session.commit()
    return settings

async def show_word(message_or_callback, state: FSMContext, new_word: bool = True):
    if isinstance(message_or_callback, types.Message):
        user_id = message_or_callback.from_user.id
        answer_func = message_or_callback.answer
        edit_func = None
    else:
        user_id = message_or_callback.from_user.id
        answer_func = None
        edit_func = message_or_callback.message.edit_text

    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if not user:
            text = "❌ Вы не зарегистрированы. Напишите /start."
            if edit_func:
                await edit_func(text)
            else:
                await answer_func(text)
            return

        settings = await get_or_create_settings(user.id, session)
        difficulty = settings.difficulty

        learned = await session.scalars(
            select(LearnedWord.word).where(LearnedWord.user_id == user.id)
        )
        exclude_list = list(learned)

        if new_word:
            word_data = await generate_word(difficulty, exclude_list)
            await state.update_data(current_word=word_data["word"])
            await state.update_data(current_word_data=word_data)
        else:
            data = await state.get_data()
            word_data = data.get("current_word_data")
            if not word_data:
                word_data = await generate_word(difficulty, exclude_list)
                await state.update_data(current_word=word_data["word"])
                await state.update_data(current_word_data=word_data)

        if word_data["word"] in exclude_list:
            word_data = await generate_word(difficulty, exclude_list)
            await state.update_data(current_word=word_data["word"])
            await state.update_data(current_word_data=word_data)

        text = (
            f"📚 *Слово дня*\n\n"
            f"*{word_data['word']}*\n"
            f"_{word_data.get('transcription', '')}_\n\n"
            f"📖 {word_data['translation']}\n"
            f"*Пример:* {word_data['example']}"
        )
        keyboard = get_word_keyboard(word_data["word"])

        if edit_func:
            await edit_func(text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await answer_func(text, parse_mode="Markdown", reply_markup=keyboard)

@router.message(Command("words"))
async def cmd_words(message: types.Message, state: FSMContext):
    await show_word(message, state, new_word=True)

@router.message(lambda message: message.text == "📚 Слова дня")
async def text_words(message: types.Message, state: FSMContext):
    await show_word(message, state, new_word=True)

@router.callback_query(lambda c: c.data == "next_word")
async def next_word_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await show_word(callback, state, new_word=True)

@router.callback_query(lambda c: c.data.startswith("learn_"))
async def learn_word_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    word = callback.data.split("_", 1)[1]
    user_id = callback.from_user.id

    data = await state.get_data()
    word_data = data.get("current_word_data", {})
    translation = word_data.get("translation", "")

    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if not user:
            await callback.message.edit_text("❌ Ошибка: пользователь не найден.")
            return

        existing = await session.scalar(
            select(LearnedWord).where(
                LearnedWord.user_id == user.id,
                LearnedWord.word == word
            )
        )
        if not existing:
            learned = LearnedWord(user_id=user.id, word=word, translation=translation)
            session.add(learned)
            await session.commit()
            await callback.message.edit_text(
                f"✅ Слово *{word}*" + (f" — {translation}" if translation else "") + " добавлено в выученные!",
                parse_mode="Markdown"
            )
        else:
            await callback.message.edit_text(f"ℹ️ Слово *{word}* уже было выучено.", parse_mode="Markdown")

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="📚 Следующее слово", callback_data="next_word")],
            [InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]
        ]
    )
    await callback.message.answer("Хочешь выучить ещё одно слово?", reply_markup=keyboard)

@router.callback_query(lambda c: c.data == "settings")
async def settings_callback(callback: types.CallbackQuery):
    await callback.answer()
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Лёгкий", callback_data="set_easy"),
             InlineKeyboardButton(text="🟡 Средний", callback_data="set_medium")],
            [InlineKeyboardButton(text="🔴 Сложный", callback_data="set_hard")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
        ]
    )
    await callback.message.edit_text(
        "⚙️ *Настройки сложности*\n\nВыбери уровень слов:",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

@router.callback_query(lambda c: c.data.startswith("set_"))
async def set_difficulty_callback(callback: types.CallbackQuery):
    await callback.answer()
    difficulty = callback.data.split("_")[1]
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if not user:
            await callback.message.edit_text("❌ Ошибка: пользователь не найден.")
            return
        settings = await get_or_create_settings(user.id, session)
        settings.difficulty = difficulty
        await session.commit()

    await callback.message.edit_text(
        f"✅ Сложность изменена на *{difficulty}*.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад в меню", callback_data="back_to_menu")]]
        )
    )

@router.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.delete()
    await show_menu(callback.message)

async def show_translate(message_or_callback):
    text = "🔤 *Переводчик*\n\nНажми на кнопку «Переводчик» в меню, чтобы начать."
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(text, parse_mode="Markdown", reply_markup=get_back_keyboard())
    else:
        await message_or_callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_back_keyboard())

async def show_progress(message_or_callback):
    if isinstance(message_or_callback, types.Message):
        user_id = message_or_callback.from_user.id
        answer_func = message_or_callback.answer
        edit_func = None
    else:
        user_id = message_or_callback.from_user.id
        answer_func = None
        edit_func = message_or_callback.message.edit_text

    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if not user:
            text = "❌ Вы не зарегистрированы. Напишите /start."
            if edit_func:
                await edit_func(text)
            else:
                await answer_func(text)
            return

        learned_count = await session.scalar(
            select(func.count()).select_from(LearnedWord).where(LearnedWord.user_id == user.id)
        )
        result = await session.execute(
            select(LearnedWord.word, LearnedWord.translation)
            .where(LearnedWord.user_id == user.id)
            .limit(20)
        )
        word_list = result.all()

        if learned_count == 0:
            text = "📊 *Мой прогресс*\n\nВы ещё не выучили ни одного слова."
        else:
            text = f"📊 *Мой прогресс*\n\n✅ Выучено слов: *{learned_count}*\n\n"
            if word_list:
                text += "📝 *Последние выученные:*\n" + "\n".join(
                    f"• {w} — {t}" if t else f"• {w}" for w, t in word_list
                )
            else:
                text += "Нет недавних слов."

        keyboard = get_back_keyboard()
        if edit_func:
            await edit_func(text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await answer_func(text, parse_mode="Markdown", reply_markup=keyboard)

# ---------- Список для изучения ----------
async def show_study_list(message_or_callback):
    if isinstance(message_or_callback, types.Message):
        user_id = message_or_callback.from_user.id
        answer_func = message_or_callback.answer
        edit_func = None
    else:
        user_id = message_or_callback.from_user.id
        answer_func = None
        edit_func = message_or_callback.message.edit_text

    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if not user:
            text = "❌ Вы не зарегистрированы. Напишите /start."
            if edit_func:
                await edit_func(text)
            else:
                await answer_func(text)
            return

        study_words = await session.scalars(
            select(StudyWord).where(StudyWord.user_id == user.id)
        )
        words = list(study_words)

        if not words:
            text = "📚 *Список для изучения*\n\nУ вас пока нет слов в списке."
        else:
            text = "📚 *Список для изучения*\n\n"
            for i, w in enumerate(words, 1):
                text += f"{i}. *{w.word}* — {w.translation}\n"
            text += "\nЧтобы удалить слово, нажмите на кнопку ниже."

        keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🗑 Очистить список", callback_data="clear_study_list")],
                [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
            ]
        )
        if edit_func:
            await edit_func(text, parse_mode="Markdown", reply_markup=keyboard)
        else:
            await answer_func(text, parse_mode="Markdown", reply_markup=keyboard)

@router.message(lambda message: message.text == "📚 Список для изучения")
async def text_study_list(message: types.Message):
    await show_study_list(message)

@router.callback_query(lambda c: c.data == "clear_study_list")
async def clear_study_list_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    user_id = callback.from_user.id
    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if not user:
            await callback.message.edit_text("❌ Пользователь не найден.")
            return
        await session.execute(
            delete(StudyWord).where(StudyWord.user_id == user.id)
        )
        await session.commit()
        await callback.message.edit_text("✅ Список очищен.", reply_markup=get_back_keyboard())

# ---------- Основное меню ----------
async def show_menu(message_or_callback):
    text = "📋 *Главное меню*\n\nВыберите раздел:"
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(text, parse_mode="Markdown", reply_markup=get_main_keyboard())
    else:
        await message_or_callback.message.edit_text(text, parse_mode="Markdown", reply_markup=get_main_keyboard())

@router.message(Command("menu"))
async def cmd_menu(message: types.Message):
    await show_menu(message)

@router.message(Command("back"))
async def cmd_back(message: types.Message):
    await show_menu(message)

@router.callback_query(lambda c: c.data.startswith("menu_"))
async def process_menu_callback(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    action = callback.data.split("_")[1]
    if action == "words":
        await show_word(callback, state, new_word=True)
    elif action == "translate":
        await show_translate(callback)
    elif action == "battle":
        await callback.message.delete()
        await start_battle_search(callback.message, state)
    elif action == "progress":
        await show_progress(callback)
    elif action == "study":
        await show_study_list(callback)
    else:
        await callback.message.answer("Неизвестный раздел")

@router.message(lambda message: message.text == "🔤 Переводчик")
async def text_translate(message: types.Message, state: FSMContext):
    from .translate import cmd_translate
    await cmd_translate(message, state)

@router.message(lambda message: message.text == "⚔️ Соревнования")
async def text_battle(message: types.Message, state: FSMContext):
    await start_battle_search(message, state)

@router.message(lambda message: message.text == "📊 Мой прогресс")
async def text_progress(message: types.Message):
    await show_progress(message)

# Обработчик для "📚 Слова дня" уже есть выше
