from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с основными разделами (всегда внизу)."""
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
        ],
        resize_keyboard=True,   # чтобы кнопки были компактными
        one_time_keyboard=False # чтобы оставалась всегда
    )