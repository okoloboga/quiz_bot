from typing import Callable, Dict, Any, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message
from aiogram.fsm.context import FSMContext

from services.google_sheets import GoogleSheetsService
from handlers.states import Registration


class AccessMiddleware(BaseMiddleware):
    def __init__(self):
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        user_id = str(event.from_user.id)
        google_sheets: GoogleSheetsService = data["google_sheets"]
        state: FSMContext = data["state"]

        # Игнорируем сообщения от администратора или владельца бота
        # if user_id == Config.ADMIN_TELEGRAM_ID or user_id == Config.OWNER_TELEGRAM_ID:
        #     return await handler(event, data)

        user_status = await google_sheets.get_user_status(user_id)
        current_state = await state.get_state()

        # Если пользователь не зарегистрирован (статуса нет) и не находится в процессе регистрации
        if user_status is None and not current_state in [
            Registration.waiting_for_phone,
            Registration.waiting_for_fio,
            Registration.waiting_for_motorcade
        ]:
            if event.text != "/start": # Разрешаем команду /start для начала регистрации
                await event.answer("Ваша учетная запись не найдена. Пожалуйста, начните регистрацию командой /start.")
                return
            # Если это /start, то пропускаем, чтобы начать регистрацию
        
        # Если пользователь не подтвержден и не находится в процессе регистрации
        if user_status not in ["подтверждён", None] and not current_state in [
            Registration.waiting_for_phone,
            Registration.waiting_for_fio,
            Registration.waiting_for_motorcade
        ]:
            await event.answer(f"Ваша учетная запись ожидает подтверждения администратором. Статус: {user_status}. Доступ к функционалу ограничен.")
            return

        return await handler(event, data)
