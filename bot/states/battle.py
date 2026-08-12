from aiogram.fsm.state import State, StatesGroup

class BattleStates(StatesGroup):
    waiting_for_opponent = State()
    battle_active = State()
    waiting_for_invite = State()   # <-- добавлено
