from aiogram.fsm.state import State, StatesGroup

class BattleStates(StatesGroup):
    waiting_for_opponent = State()   # в очереди
    battle_active = State()          # в процессе битвы