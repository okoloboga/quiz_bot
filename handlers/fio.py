import logging
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters.callback_data import CallbackData
from handlers.common import TestStates

logger = logging.getLogger(__name__)

router = Router()


class FioCallback(CallbackData, prefix="fio"):
    action: str  # "confirm" или "retry"


@router.message(TestStates.COLLECT_FIO, F.text)
async def process_fio(message: Message, state: FSMContext):
    """Обрабатывает ввод ФИО."""
    fio = message.text.strip()
    
    if len(fio) < 3:
        await message.answer("ФИО слишком короткое. Пожалуйста, введите полное ФИО.")
        return
    
    await state.update_data(fio=fio)
    await state.set_state(TestStates.CONFIRM_FIO)
    
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="Подтвердить", callback_data=FioCallback(action="confirm").pack()),
            InlineKeyboardButton(text="Ввести снова", callback_data=FioCallback(action="retry").pack())
        ]
    ])
    
    await message.answer(
        f"Ваше ФИО: {fio}\n\nПодтвердите или введите заново.",
        reply_markup=keyboard
    )


@router.callback_query(TestStates.CONFIRM_FIO, FioCallback.filter(F.action == "confirm"))
async def confirm_fio(callback: CallbackQuery, state: FSMContext):
    """Подтверждение ФИО."""
    data = await state.get_data()
    fio = data.get("fio")
    
    await callback.message.edit_text(f"ФИО подтверждено: {fio}\n\nНачинаем подготовку теста...")
    await state.set_state(TestStates.PREPARE_TEST)
    await callback.answer()
    
    # Вызываем подготовку теста (импорт здесь безопасен, т.к. test не импортирует fio)
    from handlers.test import prepare_test
    await prepare_test(callback.message, state)


@router.callback_query(TestStates.CONFIRM_FIO, FioCallback.filter(F.action == "retry"))
async def retry_fio(callback: CallbackQuery, state: FSMContext):
    """Повторный ввод ФИО."""
    await state.set_state(TestStates.COLLECT_FIO)
    await callback.message.edit_text("Пожалуйста, введите ваше ФИО заново.")
    await callback.answer()

