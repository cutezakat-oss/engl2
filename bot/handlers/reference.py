from aiogram import Router, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from sqlalchemy import select
from bot.database import AsyncSessionLocal
from bot.models import User, LearnedWord
from bot.handlers.menu import show_word

router = Router()

# ---------- База правил ----------
GRAMMAR_RULES = {
    "tenses": {
        "name": "Времена английского глагола",
        "sections": {
            "present_simple": {
                "name": "Present Simple",
                "text": "Используется для обозначения регулярных действий, фактов, расписаний.\n\nФормула: V1 (he/she/it + V1+s/es)\n\nПример: I work. He works.",
                "example_words": ["work", "play", "go", "study"]
            },
            "present_continuous": {
                "name": "Present Continuous",
                "text": "Используется для действий, происходящих сейчас, или временных ситуаций.\n\nФормула: to be (am/is/are) + Ving\n\nПример: I am working.",
                "example_words": ["working", "playing", "going", "studying"]
            },
            "past_simple": {
                "name": "Past Simple",
                "text": "Используется для завершённых действий в прошлом.\n\nФормула: V2 (правильные +ed, неправильные – вторая форма)\n\nПример: I worked. I went.",
                "example_words": ["worked", "played", "went", "studied"]
            },
            "future_simple": {
                "name": "Future Simple (will)",
                "text": "Используется для спонтанных решений, обещаний, предсказаний.\n\nФормула: will + V1\n\nПример: I will work.",
                "example_words": ["work", "play", "go", "study"]
            },
            "present_perfect": {
                "name": "Present Perfect",
                "text": "Используется для действий, которые произошли в прошлом, но имеют результат в настоящем, или для опыта.\n\nФормула: have/has + V3 (причастие прошедшего времени)\n\nПример: I have worked.",
                "example_words": ["worked", "played", "gone", "studied"]
            }
        }
    },
    "articles": {
        "name": "Артикли",
        "sections": {
            "indefinite_article": {
                "name": "Неопределённый артикль (a/an)",
                "text": "Используется перед исчисляемыми существительными в единственном числе, когда говорим о чём-то впервые или неконкретном.\n\nПример: I saw a cat. (какую-то кошку)",
                "example_words": ["cat", "dog", "apple", "house"]
            },
            "definite_article": {
                "name": "Определённый артикль (the)",
                "text": "Используется, когда речь идёт о чём-то конкретном, известном собеседнику.\n\nПример: The cat is sleeping. (именно та кошка, о которой говорили)",
                "example_words": ["cat", "dog", "apple", "house"]
            },
            "zero_article": {
                "name": "Нулевой артикль",
                "text": "Артикль не используется с неисчисляемыми существительными, именами собственными, названиями видов спорта, приёмами пищи, и т.д.\n\nПример: I like milk. He plays football.",
                "example_words": ["milk", "football", "music", "love"]
            }
        }
    },
    "modal_verbs": {
        "name": "Модальные глаголы",
        "sections": {
            "can": {
                "name": "Can (мочь, уметь)",
                "text": "Используется для выражения способности или возможности.\n\nПример: I can swim.",
                "example_words": ["swim", "run", "speak", "sing"]
            },
            "must": {
                "name": "Must (должен)",
                "text": "Выражает обязанность или необходимость.\n\nПример: You must study.",
                "example_words": ["study", "work", "read", "write"]
            },
            "may": {
                "name": "May (можно, может быть)",
                "text": "Выражает разрешение или предположение.\n\nПример: May I come in?",
                "example_words": ["come", "go", "enter", "ask"]
            }
        }
    }
}

# ---------- Отображение разделов справочника ----------
async def show_reference_menu(message_or_callback):
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=data["name"], callback_data=f"ref_section_{key}")]
            for key, data in GRAMMAR_RULES.items()
        ] + [
            [InlineKeyboardButton(text="🎲 Получить случайное слово", callback_data="ref_random_word")],
            [InlineKeyboardButton(text="🔙 Назад в главное меню", callback_data="back_to_menu")]
        ]
    )
    text = "📖 *Справочник по английской грамматике*\n\nВыберите раздел или получите случайное слово:"
    if isinstance(message_or_callback, types.Message):
        await message_or_callback.answer(text, parse_mode="HTML", reply_markup=keyboard)
    else:
        await message_or_callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)

@router.message(Command("reference"))
async def cmd_reference(message: types.Message):
    await show_reference_menu(message)

# ---------- Обработчик кнопки "🎲 Получить случайное слово" ----------
@router.callback_query(lambda c: c.data == "ref_random_word")
async def ref_random_word(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    await show_word(callback, state, new_word=True)

# ---------- Показ подразделов внутри раздела ----------
@router.callback_query(lambda c: c.data.startswith("ref_section_"))
async def show_section_menu(callback: types.CallbackQuery):
    await callback.answer()
    section_key = callback.data.split("_", 2)[2]
    section_data = GRAMMAR_RULES.get(section_key)
    if not section_data:
        await callback.message.edit_text("❌ Раздел не найден.")
        return

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=data["name"], callback_data=f"ref_rule_{section_key}|{subkey}")]
            for subkey, data in section_data["sections"].items()
        ] + [
            [InlineKeyboardButton(text="🔙 Назад к разделам", callback_data="ref_back_to_sections")]
        ]
    )
    await callback.message.edit_text(
        f"📖 *{section_data['name']}*\n\nВыберите правило:",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.callback_query(lambda c: c.data == "ref_back_to_sections")
async def back_to_sections(callback: types.CallbackQuery):
    await callback.answer()
    await show_reference_menu(callback)

# ---------- Показ конкретного правила с кнопками для слов ----------
@router.callback_query(lambda c: c.data.startswith("ref_rule_"))
async def show_rule(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data_part = callback.data.split("_", 2)[2]
    section_key, rule_key = data_part.split("|", 1)
    
    section_data = GRAMMAR_RULES.get(section_key)
    if not section_data:
        await callback.message.edit_text("❌ Раздел не найден.")
        return
    rule_data = section_data["sections"].get(rule_key)
    if not rule_data:
        await callback.message.edit_text("❌ Правило не найдено.")
        return

    text = f"📖 *{rule_data['name']}*\n\n{rule_data['text']}"

    example_words = rule_data.get("example_words", [])
    word_buttons = []
    if example_words:
        row = []
        for word in example_words:
            row.append(InlineKeyboardButton(text=word, callback_data=f"ref_word_{word}"))
            if len(row) == 3:
                word_buttons.append(row)
                row = []
        if row:
            word_buttons.append(row)

    nav_buttons = [
        [InlineKeyboardButton(text="🔙 Назад к правилам", callback_data=f"ref_section_{section_key}")],
        [InlineKeyboardButton(text="🔙 Назад в разделы", callback_data="ref_back_to_sections")]
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=word_buttons + nav_buttons)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    await state.update_data(current_rule_section=section_key, current_rule_key=rule_key)

# ---------- Обработчик нажатия на слово в правиле ----------
@router.callback_query(lambda c: c.data.startswith("ref_word_"))
async def handle_ref_word(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    word = callback.data.split("_", 2)[2]

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="✅ Добавить в выученные", callback_data=f"ref_learn_{word}")],
            [InlineKeyboardButton(text="🔙 Назад к правилу", callback_data="ref_back_to_rule")]
        ]
    )
    await callback.message.edit_text(
        f"📝 Слово: <b>{word}</b>\n\nХотите добавить его в список выученных?",
        parse_mode="HTML",
        reply_markup=keyboard
    )

@router.callback_query(lambda c: c.data.startswith("ref_learn_"))
async def ref_learn_word(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    word = callback.data.split("_", 2)[2]
    user_id = callback.from_user.id

    async with AsyncSessionLocal() as session:
        user = await session.scalar(select(User).where(User.telegram_id == user_id))
        if not user:
            await callback.message.edit_text("❌ Вы не зарегистрированы.")
            return

        existing = await session.scalar(
            select(LearnedWord).where(
                LearnedWord.user_id == user.id,
                LearnedWord.word == word
            )
        )
        if not existing:
            learned = LearnedWord(user_id=user.id, word=word, translation="")
            session.add(learned)
            await session.commit()
            await callback.message.edit_text(f"✅ Слово <b>{word}</b> добавлено в выученные!", parse_mode="HTML")
        else:
            await callback.message.edit_text(f"ℹ️ Слово <b>{word}</b> уже выучено.", parse_mode="HTML")

# ---------- ИСПРАВЛЕННЫЙ ОБРАБОТЧИК "Назад к правилу" ----------
@router.callback_query(lambda c: c.data == "ref_back_to_rule")
async def ref_back_to_rule(callback: types.CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    section_key = data.get("current_rule_section")
    rule_key = data.get("current_rule_key")
    if not section_key or not rule_key:
        await callback.message.edit_text("❌ Ошибка: не найдено текущее правило.")
        return
    
    section_data = GRAMMAR_RULES.get(section_key)
    if not section_data:
        await callback.message.edit_text("❌ Раздел не найден.")
        return
    rule_data = section_data["sections"].get(rule_key)
    if not rule_data:
        await callback.message.edit_text("❌ Правило не найдено.")
        return

    text = f"📖 *{rule_data['name']}*\n\n{rule_data['text']}"

    example_words = rule_data.get("example_words", [])
    word_buttons = []
    if example_words:
        row = []
        for word in example_words:
            row.append(InlineKeyboardButton(text=word, callback_data=f"ref_word_{word}"))
            if len(row) == 3:
                word_buttons.append(row)
                row = []
        if row:
            word_buttons.append(row)

    nav_buttons = [
        [InlineKeyboardButton(text="🔙 Назад к правилам", callback_data=f"ref_section_{section_key}")],
        [InlineKeyboardButton(text="🔙 Назад в разделы", callback_data="ref_back_to_sections")]
    ]

    keyboard = InlineKeyboardMarkup(inline_keyboard=word_buttons + nav_buttons)

    await callback.message.edit_text(text, parse_mode="HTML", reply_markup=keyboard)
    # Состояние уже содержит актуальные данные, ничего не меняем

# ---------- Кнопка "Назад" из справочника ----------
@router.callback_query(lambda c: c.data == "back_to_menu")
async def back_to_menu_from_reference(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.delete()
    from bot.handlers.menu import show_menu
    await show_menu(callback.message)
