from aiogram.fsm.state import State, StatesGroup

class TranslateStates(StatesGroup):
    waiting_for_text = State()  # ожидаем текст для перевода