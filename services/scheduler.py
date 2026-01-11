"""Scheduler service for background tasks."""
import logging

from aiogram import Bot
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from services.google_sheets import GoogleSheetsService
from services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class SchedulerService:
    """Service for scheduling background tasks."""

    def __init__(self, bot: Bot, google_sheets: GoogleSheetsService):
        """Initialize scheduler service.

        Args:
            bot: Bot instance for sending messages
            google_sheets: Google Sheets service instance
        """
        self.bot = bot
        self.google_sheets = google_sheets
        self.notification_service = NotificationService(google_sheets)
        self.scheduler = AsyncIOScheduler(timezone="Europe/Moscow")

        logger.info("SchedulerService initialized with timezone Europe/Moscow")

    def start(self):
        """Start the scheduler and add jobs."""
        # Add deadline check job - runs daily at 10:00 AM Moscow time
        self.scheduler.add_job(
            self.check_deadlines_job,
            "cron",
            hour=10,
            minute=0,
            id="deadline_check",
            name="Daily Deadline Check",
            replace_existing=True,
        )

        self.scheduler.start()
        logger.info("Scheduler started with daily deadline check at 10:00 AM")

    def shutdown(self):
        """Gracefully shutdown the scheduler."""
        if self.scheduler.running:
            self.scheduler.shutdown(wait=True)
            logger.info("Scheduler shut down successfully")

    async def check_deadlines_job(self):
        """Daily job to check campaign deadlines and send reminders.

        This job:
        1. Gets all active campaigns with deadlines in 3 or 1 day
        2. Finds users who haven't completed them
        3. Sends reminder messages via bot
        """
        logger.info("Running deadline check job")

        try:
            users_to_notify = self.notification_service.get_users_to_notify()

            if not users_to_notify:
                logger.info("No users to notify today")
                return

            sent_count = 0
            error_count = 0

            for user, campaign, days_left in users_to_notify:
                try:
                    message = self.notification_service.build_reminder_message(
                        campaign, days_left
                    )

                    if not message:
                        logger.warning(
                            f"Empty message for campaign {campaign.name} "
                            f"with {days_left} days left"
                        )
                        continue

                    await self.bot.send_message(
                        int(user.telegram_id), message, parse_mode="Markdown"
                    )

                    sent_count += 1
                    logger.info(
                        f"Sent reminder to {user.telegram_id} "
                        f"for campaign {campaign.name} "
                        f"({days_left} days left)"
                    )

                except Exception as e:
                    error_count += 1
                    logger.error(
                        f"Failed to send reminder to {user.telegram_id} "
                        f"for campaign {campaign.name}: {e}",
                        exc_info=True,
                    )

            logger.info(
                f"Deadline check completed: {sent_count} sent, "
                f"{error_count} errors"
            )

        except Exception as e:
            logger.error(
                f"Error in check_deadlines_job: {e}", exc_info=True
            )
