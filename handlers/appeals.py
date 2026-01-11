"""User appeals handler for sending messages to owner."""
import logging
from datetime import datetime

from aiogram import Router, F, Bot
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup
from aiogram.types import InlineKeyboardButton

from config import Config
from handlers.states import Appeal

logger = logging.getLogger(__name__)
router = Router()


@router.message(Command("appeal"))
async def cmd_appeal(message: Message, state: FSMContext):
    """Start appeal flow.

    Args:
        message: Command message from user
        state: FSM context
    """
    if not Config.OWNER_TELEGRAM_ID:
        await message.answer(
            "❌ Функция обращений к владельцу временно недоступна."
        )
        return

    await state.set_state(Appeal.waiting_for_message)
    await message.answer(
        "📨 Напишите ваше обращение к администратору.\n\n"
        "Вы можете отменить отправку командой /cancel."
    )
    logger.info(f"User {message.from_user.id} started appeal flow")


@router.message(Appeal.waiting_for_message, F.text)
async def process_appeal_message(message: Message, state: FSMContext):
    """Process appeal message and ask for confirmation.

    Args:
        message: User's appeal message
        state: FSM context
    """
    appeal_text = message.text.strip()

    if len(appeal_text) < 10:
        await message.answer(
            "⚠️ Сообщение слишком короткое. "
            "Пожалуйста, опишите вашу проблему подробнее."
        )
        return

    await state.update_data(appeal_text=appeal_text)
    await state.set_state(Appeal.confirm_send)

    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Отправить", callback_data="appeal_confirm"
                ),
                InlineKeyboardButton(
                    text="❌ Отменить", callback_data="appeal_cancel"
                ),
            ]
        ]
    )

    await message.answer(
        f"📋 Ваше обращение:\n\n{appeal_text}\n\n" "Отправить администратору?",
        reply_markup=keyboard,
    )


@router.callback_query(Appeal.confirm_send, F.data == "appeal_confirm")
async def confirm_appeal(callback: CallbackQuery, state: FSMContext, bot: Bot):
    """Send appeal to owner.

    Args:
        callback: Callback from confirmation button
        state: FSM context
        bot: Bot instance
    """
    data = await state.get_data()
    appeal_text = data.get("appeal_text")
    user = callback.from_user

    owner_id = Config.OWNER_TELEGRAM_ID
    message_text = (
        f"📨 Обращение от пользователя\n\n"
        f"👤 Пользователь: @{user.username or 'нет username'}\n"
        f"🆔 Telegram ID: {user.id}\n"
        f"👨‍💼 Имя: {user.first_name} {user.last_name or ''}\n"
        f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M')}\n\n"
        f"💬 Сообщение:\n{appeal_text}"
    )

    try:
        await bot.send_message(int(owner_id), message_text)
        await callback.message.edit_text(
            "✅ Ваше обращение отправлено администратору."
        )
        logger.info(f"Appeal forwarded from user {user.id} to owner {owner_id}")
    except Exception as e:
        logger.error(f"Failed to send appeal: {e}", exc_info=True)
        await callback.message.edit_text(
            "❌ Ошибка отправки. Попробуйте позже или обратитесь напрямую."
        )

    await state.clear()
    await callback.answer()


@router.callback_query(Appeal.confirm_send, F.data == "appeal_cancel")
async def cancel_appeal(callback: CallbackQuery, state: FSMContext):
    """Cancel appeal.

    Args:
        callback: Callback from cancel button
        state: FSM context
    """
    await callback.message.edit_text("❌ Обращение отменено.")
    await state.clear()
    await callback.answer()
    logger.info(f"User {callback.from_user.id} cancelled appeal")


@router.message(Command("cancel"), Appeal.waiting_for_message)
@router.message(Command("cancel"), Appeal.confirm_send)
async def cancel_appeal_command(message: Message, state: FSMContext):
    """Cancel appeal via /cancel command.

    Args:
        message: Cancel command message
        state: FSM context
    """
    await message.answer("❌ Обращение отменено.")
    await state.clear()
    logger.info(f"User {message.from_user.id} cancelled appeal via command")
