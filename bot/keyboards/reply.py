from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="📚 Слова дня"),
                KeyboardButton(text="🔤 Переводчик"),
            ],
            [
                KeyboardButton(text="⚔️ Соревнования"),
                KeyboardButton(text="📊 Мой прогресс"),
            ],
            [
                KeyboardButton(text="❌ Отменить поиск"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )

def get_battle_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура, отображаемая во время активной битвы."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="🚪 Выйти из боя"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
