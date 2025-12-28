from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from handlers.states import Registration
from services.google_sheets import GoogleSheetsService


router = Router()


@router.message(Command("start"))
async def cmd_start_registration(message: Message, state: FSMContext, google_sheets: GoogleSheetsService):
    """
    Начало флоу регистрации или приветствие для существующих пользователей.
    """
    user_id = str(message.from_user.id)
    user_status = await google_sheets.get_user_status(user_id)

    if user_status == "подтверждён":
        await message.answer("Добро пожаловать обратно! Вы уже зарегистрированы и подтверждены.")
        await state.clear() # Очищаем возможное предыдущее состояние
        # Здесь можно добавить логику для начала кампании или общего теста
    elif user_status in ["ожидает", "отклонён"]:
        await message.answer(f"Ваша учетная запись находится в статусе '{user_status}'. Пожалуйста, дождитесь подтверждения администратором.")
        await state.clear()
    else: # Пользователь не найден, запускаем регистрацию
        await message.answer(
            "Добро пожаловать! Для регистрации, пожалуйста, введите ваш номер телефона.",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(Registration.waiting_for_phone)


@router.message(Registration.waiting_for_phone, F.text)
async def process_phone(message: Message, state: FSMContext):
    """
    Обрабатывает введенный номер телефона.
    """
    phone_number = message.text
    # Здесь можно добавить валидацию номера телефона, например, через регулярные выражения
    await state.update_data(phone_number=phone_number)
    await message.answer("Спасибо! Теперь введите ваше полное ФИО.")
    await state.set_state(Registration.waiting_for_fio)


@router.message(Registration.waiting_for_fio, F.text)
async def process_fio(message: Message, state: FSMContext):
    """
    Обрабатывает введенное ФИО.
    """
    fio = message.text
    await state.update_data(fio=fio)
    await message.answer("Отлично! Назовите вашу автоколонну.")
    await state.set_state(Registration.waiting_for_motorcade)


@router.message(Registration.waiting_for_motorcade, F.text)
async def process_motorcade(message: Message, state: FSMContext, google_sheets: GoogleSheetsService):
    """
    Обрабатывает название автоколонны и завершает регистрацию.
    """
    motorcade = message.text
    data = await state.get_data()
    user_id = str(message.from_user.id)
    phone_number = data.get("phone_number")
    fio = data.get("fio")

    await google_sheets.add_user(user_id, phone_number, fio, motorcade, "ожидает")

    await message.answer(
        "Регистрация завершена! Ваша учетная запись ожидает подтверждения администратором."
    )
    await state.clear()
