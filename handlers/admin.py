"""Admin commands handler for analytics and management."""
import logging

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from middlewares.admin_filter import IsAdmin
from models import CampaignStats
from services.google_sheets import GoogleSheetsService

logger = logging.getLogger(__name__)
router = Router()


def format_campaign_stats(stats: CampaignStats) -> str:
    """Format campaign statistics for display.

    Args:
        stats: Campaign statistics object

    Returns:
        Formatted string with emoji and statistics
    """
    return (
        f"📌 **{stats.campaign_name}**\n"
        f"   Всего попыток: {stats.total_attempts}\n"
        f"   ✅ Пройдено: {stats.passed_count}\n"
        f"   ❌ Не пройдено: {stats.failed_count}\n"
        f"   📊 Процент успеха: {stats.pass_rate:.1f}%\n"
        f"   🎯 Среднее верных ответов: {stats.avg_correct_answers:.1f}\n"
    )


@router.message(Command("stats_campaign"), IsAdmin())
async def cmd_stats_campaign(
    message: Message, google_sheets: GoogleSheetsService
):
    """Show campaign statistics.

    Args:
        message: Command message from admin
        google_sheets: Google Sheets service instance
    """
    try:
        # Parse optional campaign name from message
        args = message.text.split(maxsplit=1)
        campaign_name = args[1].strip() if len(args) > 1 else None

        stats_list = google_sheets.get_campaign_statistics(campaign_name)

        if not stats_list:
            if campaign_name:
                await message.answer(
                    f"📊 Нет данных по кампании '{campaign_name}'."
                )
            else:
                await message.answer(
                    "📊 Нет данных по кампаниям.\n\n"
                    "Возможно, ещё никто не проходил тесты."
                )
            return

        if campaign_name:
            response = f"📊 Статистика кампании '{campaign_name}'\n\n"
        else:
            response = "📊 Статистика всех кампаний\n\n"

        for stats in stats_list:
            response += format_campaign_stats(stats) + "\n"

        await message.answer(response, parse_mode="Markdown")
        logger.info(
            f"Admin {message.from_user.id} requested stats for "
            f"campaign: {campaign_name or 'all'}"
        )
    except Exception as e:
        logger.error(f"Error getting campaign stats: {e}", exc_info=True)
        await message.answer(
            "❌ Ошибка получения статистики. Проверьте логи."
        )


@router.message(Command("stats_user"), IsAdmin())
async def cmd_stats_user(message: Message, google_sheets: GoogleSheetsService):
    """Show test history for specific user.

    Args:
        message: Command message from admin
        google_sheets: Google Sheets service instance
    """
    try:
        # Parse telegram_id from message
        args = message.text.split(maxsplit=1)
        if len(args) < 2:
            await message.answer(
                "⚠️ Использование: /stats_user <telegram_id>\n\n"
                "Пример: /stats_user 123456789"
            )
            return

        telegram_id = args[1].strip()

        # Get user info
        user_info = google_sheets.get_user_info(telegram_id)
        if not user_info:
            await message.answer(
                f"❌ Пользователь с ID {telegram_id} не найден."
            )
            return

        # Get user results
        results = google_sheets.get_user_results(telegram_id)

        if not results:
            await message.answer(
                f"👤 Пользователь: {user_info.fio}\n"
                f"🆔 Telegram ID: {telegram_id}\n"
                f"🚗 Автоколонна: {user_info.motorcade}\n"
                f"📊 Статус: {user_info.status.value}\n\n"
                f"📝 Тестов пройдено: 0"
            )
            return

        # Sort results by date (most recent first)
        results.sort(key=lambda r: r.date, reverse=True)

        response = (
            f"👤 Пользователь: {user_info.fio}\n"
            f"🆔 Telegram ID: {telegram_id}\n"
            f"🚗 Автоколонна: {user_info.motorcade}\n"
            f"📊 Статус: {user_info.status.value}\n\n"
            f"📝 История тестов ({len(results)}):\n\n"
        )

        for idx, result in enumerate(results, 1):
            date_str = result.date.strftime("%d.%m.%Y %H:%M")
            status_emoji = "✅" if result.final_status == "успешно" else "❌"
            response += (
                f"{idx}. {status_emoji} {result.campaign_name}\n"
                f"   Дата: {date_str}\n"
                f"   Статус: {result.final_status}\n\n"
            )

        await message.answer(response)
        logger.info(
            f"Admin {message.from_user.id} requested stats for user: {telegram_id}"
        )
    except Exception as e:
        logger.error(f"Error getting user stats: {e}", exc_info=True)
        await message.answer(
            "❌ Ошибка получения данных пользователя. Проверьте логи."
        )


@router.message(Command("admin_help"), IsAdmin())
async def cmd_admin_help(message: Message):
    """Show admin commands help.

    Args:
        message: Command message from admin
    """
    help_text = (
        "🔧 **Административные команды**\n\n"
        "📊 *Статистика:*\n"
        "/stats_campaign - Статистика всех кампаний\n"
        "/stats_campaign <название> - Статистика конкретной кампании\n"
        "/stats_user <telegram_id> - История тестов пользователя\n\n"
        "ℹ️ *Справка:*\n"
        "/admin_help - Эта справка\n"
    )
    await message.answer(help_text, parse_mode="Markdown")
