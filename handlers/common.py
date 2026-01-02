import logging
from datetime import timedelta

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (CallbackQuery, InlineKeyboardButton,
                           InlineKeyboardMarkup, Message, ReplyKeyboardRemove,
                           ReplyKeyboardMarkup, KeyboardButton)

from models import CampaignType
from services.google_sheets import AdminConfigError, GoogleSheetsService
from handlers.states import Registration


logger = logging.getLogger(__name__)

router = Router()


class TestStates(StatesGroup):
    COLLECT_FIO = State()
    CONFIRM_FIO = State()
    PREPARE_TEST = State()
    ASKING = State()
    WAIT_ANSWER = State()


@router.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext, google_sheets: GoogleSheetsService):
    """
    Единый обработчик команды /start.
    - Регистрирует новых пользователей.
    - Информирует пользователей в ожидании.
    - Запускает кампании для подтвержденных пользователей.
    """
    await state.clear()
    user_id = str(message.from_user.id)

    try:
        user_info = google_sheets.get_user_info(user_id)
        user_status = user_info.status.value if user_info else None

        # Сценарий 1: Новый пользователь
        if user_status is None:
            logger.info(f"Пользователь {user_id} не найден, запуск регистрации.")
            keyboard = ReplyKeyboardMarkup(
                keyboard=[
                    [KeyboardButton(text="Отправить мой номер телефона", request_contact=True)]
                ],
                resize_keyboard=True,
                one_time_keyboard=True
            )
            await message.answer(
                "Добро пожаловать! Для регистрации, пожалуйста, нажмите кнопку ниже, чтобы отправить ваш номер телефона.",
                reply_markup=keyboard
            )
            await state.set_state(Registration.waiting_for_phone)
            return

        # Сценарий 2: Пользователь ожидает подтверждения или отклонен
        if user_status in ["ожидает", "отклонён"]:
            logger.info(f"Пользователь {user_id} имеет статус '{user_status}', доступ ограничен.")
            await message.answer(f"Ваша учетная запись находится в статусе '{user_status}'. Пожалуйста, дождитесь подтверждения администратором.")
            return

        # Сценарий 3: Подтвержденный пользователь -> ищем кампанию
        if user_status == "подтверждён":
            campaign = google_sheets.get_active_campaign_for_user(user_id)
            if campaign:
                user_data = {
                    "id": message.from_user.id, "username": message.from_user.username,
                    "first_name": message.from_user.first_name, "last_name": message.from_user.last_name,
                }
                await state.update_data(user_data=user_data, campaign_name=campaign.name, mode=campaign.type.value)

                deadline_str = campaign.deadline.strftime("%d.%m.%Y")
                message_text = (
                    f"👋 Добро пожаловать!\n\n"
                    f"Для вас доступна учебная кампания: **{campaign.name}**\n\n"
                    f"🔹 **Тип:** {campaign.type.value}\n"
                    f"🔹 **Срок прохождения:** до {deadline_str}\n\n"
                    f"Нажмите «Начать», чтобы приступить."
                )
                keyboard = InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="Начать", callback_data=f"start_campaign")]
                ])
                await message.answer(message_text, reply_markup=keyboard, parse_mode="Markdown")
                logger.info(f"Пользователю {user_id} предложена кампания '{campaign.name}'")
            else:
                await message.answer("✅ Для вас пока нет доступных учебных кампаний. Попробуйте проверить позже.")
                logger.info(f"Для пользователя {user_id} не найдено активных кампаний.")

    except AdminConfigError as e:
        logger.error(f"Критическая ошибка конфигурации: {e}")
        await message.answer("⚠️ Бот не настроен. Пожалуйста, обратитесь к администратору.")
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке /start для {user_id}: {e}", exc_info=True)
        await message.answer("Произошла ошибка. Попробуйте позже.")


@router.callback_query(F.data == "start_campaign")
async def start_campaign_callback(callback_query: CallbackQuery, state: FSMContext, google_sheets: GoogleSheetsService):
    """
    Обрабатывает нажатие кнопки "Начать кампанию".
    Проверяет конфигурацию и наличие вопросов перед стартом.
    """
    try:
        admin_config = google_sheets.read_admin_config()
        all_questions = google_sheets.read_questions()

        if not all_questions:
            await callback_query.message.answer("❗️ В базе нет вопросов для этой кампании. Обратитесь к администратору.")
            await state.clear()
            return
        
        if len(all_questions) < admin_config.num_questions:
            logger.warning(
                "Недостаточно вопросов: доступно %s, требуется %s",
                len(all_questions), admin_config.num_questions
            )
            await callback_query.message.answer("⚠️ Временно недостаточно вопросов для старта. Обратитесь к администратору.")
            await state.clear()
            return

        # Если все проверки пройдены, запрашиваем ФИО
        await state.set_state(TestStates.COLLECT_FIO)
        await callback_query.message.answer(
            "Для начала введите ваше ФИО (Фамилия Имя Отчество) одной строкой."
        )
        await callback_query.answer()
        logger.info(f"Пользователь {callback_query.from_user.id} начинает кампанию.")

    except AdminConfigError as e:
        logger.error(f"Отсутствуют настройки теста: {e}")
        await callback_query.message.answer("⚠️ У бота отсутствуют необходимые настройки. Обратитесь к администратору.")
        await state.clear()
    except Exception as e:
        logger.error(f"Ошибка при старте кампании: {e}", exc_info=True)
        await callback_query.message.answer("Произошла ошибка при подготовке к тесту. Попробуйте позже.")
        await state.clear()