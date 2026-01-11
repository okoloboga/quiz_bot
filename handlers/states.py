from aiogram.fsm.state import StatesGroup, State


class Registration(StatesGroup):
    waiting_for_phone = State()
    waiting_for_fio = State()
    waiting_for_motorcade = State()


class TestStates(StatesGroup):
    PREPARE_TEST = State()
    ASKING = State()
    WAIT_ANSWER = State()


class Appeal(StatesGroup):
    waiting_for_message = State()
    confirm_send = State()
