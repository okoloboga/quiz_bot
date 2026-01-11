"""Admin access filter for restricting commands to administrators."""
import logging
from aiogram.filters import Filter
from aiogram.types import Message

from config import Config

logger = logging.getLogger(__name__)


class IsAdmin(Filter):
    """Filter to check if user is administrator."""

    async def __call__(self, message: Message) -> bool:
        """Check if message sender is admin.

        Args:
            message: Incoming message

        Returns:
            True if user is admin, False otherwise
        """
        if not Config.ADMIN_TELEGRAM_ID:
            logger.warning("ADMIN_TELEGRAM_ID not configured")
            return False

        is_admin = str(message.from_user.id) == Config.ADMIN_TELEGRAM_ID

        if not is_admin:
            logger.info(
                f"Access denied for user {message.from_user.id} "
                f"to admin command: {message.text}"
            )

        return is_admin
