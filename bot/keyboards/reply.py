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
                KeyboardButton(text="❌ Отменить поиск"),   # Новая кнопка
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=False
    )
