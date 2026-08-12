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
                KeyboardButton(text="👤 Мой профиль"),
                KeyboardButton(text="📚 Список для изучения"),
            ],
            [
                KeyboardButton(text="❌ Отменить поиск"),
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
