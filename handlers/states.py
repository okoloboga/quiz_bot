from aiogram.fsm.state import StatesGroup, State


class Registration(StatesGroup):
    waiting_for_phone = State()
    waiting_for_fio = State()
    waiting_for_motorcade = State()


class Test(StatesGroup):
    asking_question = State()
    waiting_answer = State()
    confirm_fio = State()
