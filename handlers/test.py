import asyncio
import logging
import time
from datetime import datetime
from typing import Optional

import pytz
from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters.callback_data import CallbackData
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

from handlers.states import TestStates
from models import CampaignType, Question, Session
from services.google_sheets import GoogleSheetsService
from services.redis_service import RedisService
from utils.question_distribution import distribute_questions_by_category

logger = logging.getLogger(__name__)
router = Router()

sheets_service = GoogleSheetsService()
redis_service = RedisService()


class AnswerCallback(CallbackData, prefix="answer"):
    question_index: int
    answer: int


async def prepare_test(message: Message, state: FSMContext):
    telegram_id = message.from_user.id
    if await redis_service.has_active_session(telegram_id):
        await message.answer("⚠️ У вас уже есть активная сессия теста. Пожалуйста, завершите ее.")
        return

    try:
        admin_config = sheets_service.read_admin_config()
        all_questions = sheets_service.read_questions()
        
        if len(all_questions) < admin_config.num_questions:
            await message.answer("⚠️ В боте недостаточно вопросов. Обратитесь к администратору.")
            await state.clear()
            return

        selected_questions = distribute_questions_by_category(all_questions, admin_config.num_questions)
        actual_num = len(selected_questions)

        if actual_num < admin_config.num_questions:
            await message.answer("⚠️ Не удалось сформировать достаточное количество вопросов. Обратитесь к администратору.")
            await state.clear()
            return

        data = await state.get_data()
        session = Session(
            fio=data.get("fio"),
            question_ids=[q.row_index for q in selected_questions],
            current_index=0,
            remaining_score=admin_config.max_errors,
            correct_count=0,
            started_at=time.time(),
            last_action_at=time.time(),
            per_question_deadline=None,
            admin_config_snapshot=admin_config.__dict__,
            campaign_name=data.get("campaign_name"),
            mode=data.get("mode")
        )

        await state.update_data(
            questions=[q.__dict__ for q in selected_questions],
            session=session.to_dict()
        )

        ttl = actual_num * admin_config.seconds_per_question + 300
        await redis_service.set_session(telegram_id, session, ttl)
        await state.set_state(TestStates.ASKING)

        await message.answer(
            f"🚀 Тест начинается!\n\n"
            f"Правила:\n"
            f"• Количество вопросов: {actual_num}\n"
            f"• Время на вопрос: {admin_config.seconds_per_question} секунд\n"
            f"• Допустимых ошибок: {admin_config.max_errors}"
        )
        await ask_next_question(message, state)

    except Exception as e:
        logger.error(f"Ошибка подготовки теста: {e}", exc_info=True)
        await message.answer("❌ Произошла ошибка при подготовке теста. Попробуйте позже.")
        await state.clear()


async def ask_next_question(message: Message, state: FSMContext):
    data = await state.get_data()
    session = Session.from_dict(data.get("session", {}))
    questions_data = data.get("questions", [])

    if not session or not questions_data:
        await message.answer("⚠️ Ошибка: данные сессии не найдены.")
        await state.clear()
        return

    current_idx = session.current_index
    if current_idx >= len(questions_data):
        await finish_test(message, state, passed=True)
        return

    question = Question(**questions_data[current_idx])
    deadline = time.time() + session.admin_config_snapshot["seconds_per_question"]
    session.per_question_deadline = deadline
    session.last_action_at = time.time()

    await state.update_data(session=session.to_dict())
    telegram_id = message.from_user.id
    ttl = (len(questions_data) - current_idx) * session.admin_config_snapshot["seconds_per_question"] + 300
    await redis_service.set_session(telegram_id, session, ttl)

    answers_text = ""
    buttons = []
    for i, ans in enumerate([question.answer1, question.answer2, question.answer3, question.answer4]):
        if ans:
            answers_text += f"{i + 1}. {ans}\n"
            buttons.append(InlineKeyboardButton(text=str(i + 1),
                                                callback_data=AnswerCallback(question_index=current_idx,
                                                                             answer=i + 1).pack()))

    keyboard = InlineKeyboardMarkup(inline_keyboard=[buttons])
    question_num = current_idx + 1
    total = len(questions_data)

    await message.answer(
        f"❓ Вопрос {question_num}/{total}\n\n{question.question_text}\n\n{answers_text}",
        reply_markup=keyboard
    )
    await state.set_state(TestStates.WAIT_ANSWER)
    logger.info(f"Вопрос {question_num} отправлен пользователю {telegram_id} (row={question.row_index})")
    asyncio.create_task(check_timeout(message, state, current_idx, deadline))


async def check_timeout(message: Message, state: FSMContext, q_index: int, deadline: float):
    await asyncio.sleep(deadline - time.time() + 0.5)
    data = await state.get_data()
    session = Session.from_dict(data.get("session", {}))

    if session and session.current_index == q_index and time.time() >= deadline:
        await message.answer("⏰ Время на ответ истекло. Тест завершен.")
        await finish_test(message, state, passed=False, notes=f"таймаут на вопрос #{q_index + 1}")


@router.callback_query(TestStates.WAIT_ANSWER, AnswerCallback.filter())
async def process_answer(cb: CallbackQuery, callback_data: AnswerCallback, state: FSMContext):
    data = await state.get_data()
    session = Session.from_dict(data.get("session", {}))
    questions_data = data.get("questions", [])

    if not session or not questions_data or callback_data.question_index != session.current_index:
        await cb.answer("⚠️ Ошибка сессии или запоздалый ответ.", show_alert=True)
        return

    if time.time() > session.per_question_deadline:
        await cb.answer("⏰ Время на ответ истекло.", show_alert=True)
        await finish_test(cb.message, state, passed=False, notes=f"таймаут на вопрос #{session.current_index + 1}")
        return

    question = Question(**questions_data[session.current_index])
    is_correct = callback_data.answer == question.correct_answer

    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except TelegramBadRequest:
        pass # Сообщение не изменилось, это нормально

    if is_correct:
        session.correct_count += 1
        await cb.answer("✅ Верно!", show_alert=False)
    else:
        session.remaining_score -= 1
        await cb.answer("❌ Неверно!", show_alert=False)

        if question.is_critical:
            await cb.message.answer("Вы ошиблись в критическом вопросе. Тест завершен.")
            await finish_test(cb.message, state, passed=False, notes="неверный ответ на критический вопрос")
            return

        if session.mode == CampaignType.TRAINING and question.explanation:
            await cb.message.answer(f" пояснение: {question.explanation}")

    logger.info(
        f"Ответ п-ля {cb.from_user.id} на в. {session.current_index + 1}: "
        f"выбран={callback_data.answer}, прав={question.correct_answer}, "
        f"итог={is_correct}, баллы={session.remaining_score}"
    )

    if session.remaining_score <= 0:
        await cb.message.answer("Баллы исчерпаны. Тест завершен.")
        await finish_test(cb.message, state, passed=False, notes="закончились баллы")
        return

    session.current_index += 1
    await state.update_data(session=session.to_dict())
    await redis_service.set_session(cb.from_user.id, session)

    await asyncio.sleep(1)
    await ask_next_question(cb.message, state)


async def finish_test(message: Message, state: FSMContext, passed: bool, notes: Optional[str] = None):
    data = await state.get_data()
    user_data = data.get("user_data", {})
    session = Session.from_dict(data.get("session", {}))

    if not session or not user_data:
        logger.error(f"Не найдены данные сессии для {message.from_user.id} при завершении теста.")
        await message.answer("⚠️ Ошибка: не удалось найти данные сессии для сохранения результата.")
        await state.clear()
        return

    result_text = "Пройден" if passed else "Не пройден"
    final_status = "успешно" if passed else "не пройдено"
    campaign_name = session.campaign_name or ""  # Используем пустую строку, если имя кампании None

    try:
        tz = pytz.timezone("Europe/Moscow")
        test_date = datetime.now(tz).isoformat()
        display_name = user_data.get("username") or f"{user_data.get('first_name', '')} {user_data.get('last_name', '')}".strip()

        sheets_service.write_result(
            telegram_id=user_data["id"],
            display_name=display_name,
            test_date=test_date,
            fio=session.fio,
            result=result_text,
            correct_count=session.correct_count,
            notes=notes,
            campaign_name=campaign_name,
            final_status=final_status,
        )
    except Exception as e:
        logger.error(f"Ошибка записи результата в Google Sheets: {e}", exc_info=True)
        await message.answer("⚠️ Не удалось сохранить результат. Обратитесь к администратору.")

    total_questions = len(data.get("questions", []))
    logger.info(
        f"Тест завершен для {user_data['id']}: FIO={session.fio}, result={result_text}, "
        f"correct={session.correct_count}/{total_questions}"
    )

    test_name = f"«{campaign_name}» " if campaign_name else ""
    if passed:
        await message.answer(f"✅ Тест {test_name}успешно пройден!\n\nРезультат: {session.correct_count} из {total_questions}")
    else:
        await message.answer(f"❌ Тест {test_name}не пройден.\n\nПовторная попытка будет доступна согласно правилам.")

    await redis_service.delete_session(user_data["id"])
    await state.clear()

