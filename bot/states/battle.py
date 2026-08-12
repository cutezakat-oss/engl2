from aiogram.fsm.state import State, StatesGroup

class BattleStates(StatesGroup):
    waiting_for_opponent = State()
    battle_active = State()
    waiting_for_invite = State()           # ожидание ввода @username
    waiting_for_invite_accept = State()    # ожидание выбора сложности
