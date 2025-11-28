import asyncio
import logging
import time
from datetime import datetime
from typing import Optional
import pytz
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.filters.callback_data import CallbackData
from handlers.common import TestStates
from services.google_sheets import GoogleSheetsService, AdminConfigError
from services.redis_service import RedisService
from models import Session, AdminConfig
from utils.question_distribution import distribute_questions_by_category

logger = logging.getLogger(__name__)

router = Router()

sheets_service = GoogleSheetsService()
redis_service = RedisService()


class AnswerCallback(CallbackData, prefix="answer"):
    question_index: int
    answer: int  # 1-4


async def prepare_test(message: Message, state: FSMContext):
    """Подготавливает тест: проверяет повторные прохождения, формирует вопросы."""
    telegram_id = message.from_user.id
    
    # Проверяем активную сессию
    if await redis_service.has_active_session(telegram_id):
        await message.answer("⚠️ У вас уже есть активная сессия теста. Пожалуйста, завершите текущий тест.")
        return
    
    try:
        # Читаем конфигурацию (проверки уже были в /start)
        admin_config = sheets_service.read_admin_config()
        
        # Проверяем время последнего прохождения
        last_test_time = sheets_service.get_last_test_time(telegram_id)
        if last_test_time:
            hours_passed = (time.time() - last_test_time) / 3600
            if hours_passed < admin_config.retry_hours:
                remaining_hours = admin_config.retry_hours - hours_passed
                remaining_minutes = int((remaining_hours - int(remaining_hours)) * 60)
                await message.answer(
                    f"⏳ Вы недавно проходили тест. Следующая попытка доступна через "
                    f"{int(remaining_hours)} ч. {remaining_minutes} мин."
                )
                await state.clear()
                return
        
        # Загружаем вопросы (проверка количества уже была в /start)
        all_questions = sheets_service.read_questions()
        logger.info(f"Загружено {len(all_questions)} вопросов из таблицы")
        
        # Формируем выборку
        selected_questions = distribute_questions_by_category(all_questions, admin_config.num_questions)
        actual_num = len(selected_questions)
        
        if actual_num < admin_config.num_questions:
            logger.error(
                "Не удалось сформировать достаточно вопросов: получено %s из %s",
                actual_num,
                admin_config.num_questions,
            )
            await message.answer("⚠️ В боте недостаточно вопросов. Обратитесь к администратору.")
            await state.clear()
            return
        
        # Сохраняем данные в state
        data = await state.get_data()
        fio = data.get("fio")
        
        question_ids = [q.row_index for q in selected_questions]
        
        # Создаем сессию
        session = Session(
            fio=fio,
            question_ids=question_ids,
            current_index=0,
            remaining_score=admin_config.max_errors,
            correct_count=0,
            started_at=time.time(),
            last_action_at=time.time(),
            per_question_deadline=None,
            admin_config_snapshot={
                "num_questions": actual_num,
                "max_errors": admin_config.max_errors,
                "retry_hours": admin_config.retry_hours,
                "seconds_per_question": admin_config.seconds_per_question
            }
        )
        
        # Сохраняем вопросы в state для доступа
        await state.update_data(
            questions=[q.__dict__ for q in selected_questions],
            session=session.to_dict()
        )
        
        # Сохраняем сессию в Redis
        ttl = actual_num * admin_config.seconds_per_question + 300  # + padding
        await redis_service.set_session(telegram_id, session, ttl)
        
        await state.set_state(TestStates.ASKING)
        
        # Отправляем приветственное сообщение с правилами
        await message.answer(
            f"🚀 Тест начинается!\n\n"
            f"Правила:\n"
            f"• Количество вопросов: {actual_num}\n"
            f"• Время на вопрос: {admin_config.seconds_per_question} секунд\n"
            f"• Допустимых ошибок: {admin_config.max_errors}\n\n"
            f"При достижении 0 баллов тест завершится автоматически."
        )
        
        # Начинаем задавать вопросы
        await ask_next_question(message, state)
        
    except Exception as e:
        logger.error(f"Ошибка подготовки теста: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при подготовке теста. Попробуйте позже.")
        await state.clear()


async def ask_next_question(message: Message, state: FSMContext):
    """Задает следующий вопрос."""
    data = await state.get_data()
    questions_data = data.get("questions", [])
    session_dict = data.get("session", {})
    
    if not questions_data or not session_dict:
        await message.answer("⚠️ Ошибка: данные сессии не найдены.")
        await state.clear()
        return
    
    session = Session.from_dict(session_dict)
    current_idx = session.current_index
    
    if current_idx >= len(questions_data):
        # Все вопросы заданы
        await finish_test(message, state, passed=True)
        return
    
    # Получаем текущий вопрос
    question_data = questions_data[current_idx]
    from models import Question
    question = Question(**question_data)
    
    # Устанавливаем deadline
    deadline = time.time() + session.admin_config_snapshot["seconds_per_question"]
    session.per_question_deadline = deadline
    session.last_action_at = time.time()
    
    # Обновляем state и Redis
    await state.update_data(session=session.to_dict())
    telegram_id = message.from_user.id
    ttl = (len(questions_data) - current_idx) * session.admin_config_snapshot["seconds_per_question"] + 300
    await redis_service.set_session(telegram_id, session, ttl)
    
    # Формируем клавиатуру с вариантами ответов
    from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

    answer_buttons = []
    answer_options = [
        (question.answer1, 1),
        (question.answer2, 2),
        (question.answer3, 3),
        (question.answer4, 4),
    ]

    # Собираем текст вариантов ответов и кнопки только с цифрами
    answers_text = ""
    for text, num in answer_options:
        if text:
            answers_text += f"{num}. {text}\n"
            answer_buttons.append(
                InlineKeyboardButton(
                    text=str(num),
                    callback_data=AnswerCallback(question_index=current_idx, answer=num).pack()
                )
            )

    if len(answer_buttons) < 2:
        logger.error(f"Вопрос {question.row_index} содержит недостаточно вариантов ответов.")
        await message.answer("⚠️ Ошибка: недостаточно вариантов ответов для этого вопроса. Обратитесь к администратору.")
        await state.clear()
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[answer_buttons])

    question_num = current_idx + 1
    total = len(questions_data)

    await message.answer(
        f"❓ Вопрос {question_num}/{total}\n\n"
        f"{question.question_text}\n\n"
        f"{answers_text}",
        reply_markup=keyboard
    )
    
    await state.set_state(TestStates.WAIT_ANSWER)
    
    logger.info(f"Вопрос {question_num} отправлен пользователю {telegram_id}: category={question.category}, row={question.row_index}")
    
    # Запускаем таймер
    asyncio.create_task(check_timeout(message, state, current_idx, deadline))


async def check_timeout(message: Message, state: FSMContext, question_index: int, deadline: float):
    """Проверяет таймаут для вопроса."""
    sleep_time = deadline - time.time() + 0.5
    if sleep_time > 0:
        await asyncio.sleep(sleep_time)
    
    # Проверяем, не изменился ли индекс вопроса (пользователь ответил)
    data = await state.get_data()
    session_dict = data.get("session", {})
    if session_dict:
        session = Session.from_dict(session_dict)
        if session.current_index > question_index:
            # Пользователь уже ответил
            return
    
    # Проверяем deadline
    if time.time() >= deadline:
        # Таймаут
        data = await state.get_data()
        session_dict = data.get("session", {})
        if session_dict:
            session = Session.from_dict(session_dict)
            if session.current_index == question_index:
                # Все еще на этом вопросе - таймаут
                await message.answer("⏰ Время на ответ истекло. Тест завершен.")
                await finish_test(message, state, passed=False, timeout_question=question_index + 1)


@router.callback_query(TestStates.WAIT_ANSWER, AnswerCallback.filter())
async def process_answer(callback: CallbackQuery, callback_data: AnswerCallback, state: FSMContext):
    """Обрабатывает ответ пользователя."""
    telegram_id = callback.from_user.id
    data = await state.get_data()
    questions_data = data.get("questions", [])
    session_dict = data.get("session", {})
    
    if not questions_data or not session_dict:
        await callback.answer("⚠️ Ошибка: данные сессии не найдены.")
        return
    
    session = Session.from_dict(session_dict)
    current_idx = session.current_index
    
    # Проверяем, что ответ на текущий вопрос
    if callback_data.question_index != current_idx:
        await callback.answer("ℹ️ Этот вопрос уже пройден.", show_alert=True)
        return
    
    # Проверяем таймаут
    if session.per_question_deadline and time.time() > session.per_question_deadline:
        await callback.answer("⏰ Время на ответ истекло. Тест завершен.", show_alert=True)
        await finish_test(callback.message, state, passed=False, timeout_question=current_idx + 1)
        return
    
    # Получаем вопрос
    question_data = questions_data[current_idx]
    from models import Question
    question = Question(**question_data)
    
    # Проверяем ответ
    is_correct = callback_data.answer == question.correct_answer
    
    if is_correct:
        session.correct_count += 1
    else:
        session.remaining_score -= 1
    
    logger.info(
        f"Ответ пользователя {telegram_id} на вопрос {current_idx + 1}: "
        f"выбран={callback_data.answer}, правильный={question.correct_answer}, "
        f"correct={is_correct}, remaining_score={session.remaining_score}"
    )
    
    # Просто убираем кнопки из сообщения
    question_num = current_idx + 1
    total = len(questions_data)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    
    # Проверяем, не закончились ли баллы
    if session.remaining_score <= 0:
        await callback.message.edit_text(
            f"❓ Вопрос {question_num}/{total}\n\n"
            f"{question.question_text}\n\n"
            f"❌ Баллы исчерпаны. Тест завершен."
        )
        await finish_test(callback.message, state, passed=False)
        return
    
    # Переходим к следующему вопросу
    session.current_index += 1
    session.last_action_at = time.time()
    session.per_question_deadline = None
    
    await state.update_data(session=session.to_dict())
    ttl = (len(questions_data) - session.current_index) * session.admin_config_snapshot["seconds_per_question"] + 300
    await redis_service.set_session(telegram_id, session, ttl)
    
    # Небольшая пауза перед следующим вопросом
    await asyncio.sleep(1)
    await ask_next_question(callback.message, state)


async def finish_test(message: Message, state: FSMContext, passed: bool, timeout_question: Optional[int] = None):
    """Завершает тест и сохраняет результат."""
    # Получаем данные пользователя из state (сохраняем при старте)
    data = await state.get_data()
    user_data = data.get("user_data")
    
    if not user_data:
        # Fallback на message.from_user, если не сохранено в state
        user_data = {
            "id": message.from_user.id,
            "username": message.from_user.username,
            "first_name": message.from_user.first_name,
            "last_name": message.from_user.last_name
        }
    
    telegram_id = user_data["id"]
    session_dict = data.get("session", {})
    questions_data = data.get("questions", [])
    
    if not session_dict:
        await message.answer("⚠️ Ошибка: данные сессии не найдены.")
        await state.clear()
        return
    
    session = Session.from_dict(session_dict)
    
    # Определяем результат
    result_text = "Пройден" if passed else "Не пройден"
    
    # Формируем примечания
    notes = None
    if timeout_question:
        notes = f"таймаут на вопрос #{timeout_question}"
    
    # Сохраняем в Google Sheets
    try:
        tz = pytz.timezone("Europe/Moscow")  # UTC+3
        now = datetime.now(tz)
        test_date = now.strftime("%Y-%m-%d %H:%M")
        
        if user_data.get("username"):
            display_name = user_data["username"]
        else:
            parts = [user_data.get("first_name") or '', user_data.get("last_name") or '']
            display_name = " ".join(part for part in parts if part).strip()

        sheets_service.write_result(
            telegram_id=telegram_id,
            display_name=display_name,
            test_date=test_date,
            fio=session.fio,
            result=result_text,
            correct_count=session.correct_count,
            notes=notes
        )
    except Exception as e:
        logger.error(f"Ошибка записи результата в Google Sheets: {e}")
        await message.answer(
            "⚠️ Результат не удалось сохранить в базу данных. "
            "Пожалуйста, обратитесь к администратору."
        )
    
    # Логируем результат
    logger.info(
        f"Тест завершен для пользователя {telegram_id}: "
        f"FIO={session.fio}, result={result_text}, "
        f"correct_count={session.correct_count}/{len(questions_data)}, "
        f"remaining_score={session.remaining_score}"
    )
    
    # Сообщаем пользователю
    await message.answer(
        f"🏁 Тест завершен.\n\n"
        f"Результат: {result_text}\n"
        f"Правильных ответов: {session.correct_count} из {len(questions_data)}"
    )
    
    # Удаляем сессию
    await redis_service.delete_session(telegram_id)
    await state.set_state(TestStates.FINISHED)
    await state.clear()

