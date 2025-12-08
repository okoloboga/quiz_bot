import logging
import time
from datetime import timedelta

from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
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
    WAIT_FINAL_NOTE = State()


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
    
    # Отправляем приветственное сообщение с кнопкой
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Начать", callback_data="start_test")]
    ])
    
    welcome_message = (
        "🚛 Добро пожаловать в систему обязательного тестирования водителей компании\n\n"
        "📌 Тестирование проводится по прямому указанию руководства и является обязательным для всех водителей ГК Лагранж.\n\n"
        "🎯 Цель тестов — повысить безопасность, снизить аварийность, сократить простои, сохранить технику и увеличить эффективность и зарплату.\n"
        "Знания, отработанные до автоматизма, напрямую влияют на вашу безопасность и результат.\n\n"
        "👤 Перед началом необходимо авторизоваться, указав ФИО.\n"
        "⏱️ Тест занимает не более 5 минут и включает элементарные вопросы по внутренним регламентам и технической части.\n\n"
        "📝 По завершении вы получите результат: «Пройдено» или «Не пройдено».\n"
        "Если тест не пройден, необходимо повторить материал и пересдать через 24 часа.\n\n"
        "🔁 Тесты проводятся регулярно, поэтому они короткие и направлены на закрепление ключевых правил, которые должны быть на уровне автоматизма.\n\n"
        "⚠️ Это инструмент, который сохраняет жизни, технику, время и деньги — ваши и компании.\n\n"
        "👉 Нажмите «Начать», чтобы приступить к тестированию."
    )
    
    await message.answer(welcome_message, reply_markup=keyboard)
    logger.info(f"Пользователь {message.from_user.id} получил приветственное сообщение")


@router.callback_query(F.data == "start_test")
async def start_test_callback(callback_query: CallbackQuery, state: FSMContext):
    """Обработчик нажатия кнопки 'Начать'."""
    await state.set_state(TestStates.COLLECT_FIO)
    await callback_query.message.answer(
        "Для начала теста введите ваше ФИО (Фамилия Имя Отчество) одной строкой."
    )
    await callback_query.answer()
    logger.info(f"Пользователь {callback_query.from_user.id} нажал 'Начать'")