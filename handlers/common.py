import logging
import time
from datetime import timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from services.google_sheets import GoogleSheetsService, AdminConfigError

logger = logging.getLogger(__name__)

router = Router()

sheets_service = GoogleSheetsService()


class TestStates(StatesGroup):
    START = State()
    COLLECT_FIO = State()
    CONFIRM_FIO = State()
    PREPARE_TEST = State()
    ASKING = State()
    WAIT_ANSWER = State()
    FINISHED = State()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start."""
    # Проверяем настройки сразу после /start
    try:
        admin_config = sheets_service.read_admin_config()
        logger.info(
            "Конфигурация загружена: N=%s, M=%s, H=%s, S=%s",
            admin_config.num_questions,
            admin_config.max_errors,
            admin_config.retry_hours,
            admin_config.seconds_per_question,
        )
    except AdminConfigError as e:
        logger.error(f"Отсутствуют настройки теста: {e}")
        await message.answer("⚠️ У бота отсутствуют необходимые настройки. Обратитесь к администратору.")
        await state.clear()
        return

    # Проверка на cooldown
    last_test_time = sheets_service.get_last_test_time(message.from_user.id)
    if last_test_time:
        cooldown_seconds = admin_config.retry_hours * 3600
        time_passed = time.time() - last_test_time
        
        if time_passed < cooldown_seconds:
            remaining_time = cooldown_seconds - time_passed
            # Форматируем оставшееся время в ЧЧ:ММ:СС
            td = timedelta(seconds=int(remaining_time))
            hours, remainder = divmod(td.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            remaining_str = f"{hours:02}:{minutes:02}:{seconds:02}"
            
            logger.info(
                f"Пользователь {message.from_user.id} попытался пройти тест раньше времени. "
                f"Осталось: {remaining_str}"
            )
            await message.answer(
                f"Вы уже проходили тест. Следующая попытка будет доступна через: {remaining_str}"
            )
            await state.clear()
            return
    
    # Проверяем количество вопросов
    all_questions = sheets_service.read_questions()
    if not all_questions:
        await message.answer("❗️ В базе нет вопросов. Обратитесь к администратору.")
        await state.clear()
        return
    
    if len(all_questions) < admin_config.num_questions:
        logger.error(
            "Недостаточно вопросов: доступно %s, требуется %s",
            len(all_questions),
            admin_config.num_questions,
        )
        await message.answer("⚠️ В боте недостаточно вопросов. Обратитесь к администратору.")
        await state.clear()
        return
    
    # Сохраняем данные пользователя в state
    user = message.from_user
    await state.update_data(user_data={
        "id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name
    })
    
    # Все проверки пройдены, переходим к сбору ФИО
    await state.set_state(TestStates.COLLECT_FIO)
    await message.answer(
        "👋 Добро пожаловать! Для начала теста введите ваше ФИО (Фамилия Имя Отчество) одной строкой."
    )
    logger.info(f"Пользователь {message.from_user.id} начал сессию")