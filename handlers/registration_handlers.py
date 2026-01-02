from aiogram import Router, F
from aiogram.types import Message, ReplyKeyboardRemove
from aiogram.fsm.context import FSMContext
from aiogram.filters import Command

from handlers.states import Registration
from services.google_sheets import GoogleSheetsService


router = Router()


@router.message(Registration.waiting_for_phone, F.contact)
async def process_phone(message: Message, state: FSMContext):
    """
    Обрабатывает полученный номер телефона из контакта Telegram.
    """
    phone_number = message.contact.phone_number
    await state.update_data(phone_number=phone_number)
    await message.answer("Спасибо! Теперь введите ваше полное ФИО.", reply_markup=ReplyKeyboardRemove())
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

    google_sheets.add_user(user_id, phone_number, fio, motorcade, "ожидает")

    await message.answer(
        "Регистрация завершена! Ваша учетная запись ожидает подтверждения администратором."
    )
    await state.clear()
