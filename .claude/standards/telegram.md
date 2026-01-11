# Telegram Standard

Best practices for Telegram Bot API, Mini Apps, and platform-specific features.

## Core Principles

1. **User Experience First**: Optimize for mobile Telegram clients
2. **Rate Limits Aware**: Respect Telegram API rate limits
3. **Graceful Degradation**: Handle API errors gracefully
4. **Security**: Validate all data from Telegram
5. **Localization**: Support multiple languages

---

## Telegram Bot API

### Rate Limits

**MUST respect Telegram rate limits:**

- Group messages: 20 messages per minute
- Private messages: 30 messages per second (spread across users)
- Same user: Max 1 message per second
- Bulk operations: Use `sendMediaGroup` for multiple items

```python
# services/telegram_service.py
import asyncio
from aiogram import Bot

class TelegramService:
    """Service with rate limiting."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self._semaphore = asyncio.Semaphore(20)  # 20 concurrent requests

    async def send_message_safe(self, chat_id: int, text: str):
        """Send message with rate limiting."""
        async with self._semaphore:
            try:
                return await self.bot.send_message(chat_id, text)
            except RetryAfter as e:
                await asyncio.sleep(e.timeout)
                return await self.bot.send_message(chat_id, text)
```

### Error Handling

```python
from aiogram.exceptions import (
    TelegramBadRequest,
    TelegramForbiddenError,
    TelegramAPIError
)
import structlog

logger = structlog.get_logger()

async def send_message_with_retry(bot: Bot, chat_id: int, text: str):
    """Send message with error handling."""
    try:
        return await bot.send_message(chat_id, text)

    except TelegramForbiddenError:
        # User blocked the bot
        logger.warning("user_blocked_bot", chat_id=chat_id)
        # Mark user as inactive in database
        await mark_user_inactive(chat_id)

    except TelegramBadRequest as e:
        # Invalid request (chat not found, message too long, etc.)
        logger.error("bad_request", chat_id=chat_id, error=str(e))
        raise

    except TelegramAPIError as e:
        # Generic API error, retry
        logger.error("api_error", chat_id=chat_id, error=str(e))
        await asyncio.sleep(1)
        return await bot.send_message(chat_id, text)
```

---

## Message Formatting

### Markdown V2 (Recommended)

```python
from aiogram.enums import ParseMode
from aiogram.utils.markdown import hbold, hcode, hlink

async def send_formatted_message(message: Message):
    """Send message with MarkdownV2 formatting."""
    text = (
        f"{hbold('Заголовок')}\n\n"
        f"Обычный текст\n"
        f"Код: {hcode('python main.py')}\n"
        f"{hlink('Ссылка', 'https://example.com')}"
    )

    await message.answer(text, parse_mode=ParseMode.HTML)
```

### HTML (Alternative)

```python
text = (
    "<b>Заголовок</b>\n\n"
    "Обычный текст\n"
    "Код: <code>python main.py</code>\n"
    "<a href='https://example.com'>Ссылка</a>"
)

await message.answer(text, parse_mode=ParseMode.HTML)
```

### Message Length Limits

**MUST respect message length limits:**

```python
MAX_MESSAGE_LENGTH = 4096
MAX_CAPTION_LENGTH = 1024

def split_message(text: str, max_length: int = MAX_MESSAGE_LENGTH) -> list[str]:
    """Split long message into chunks."""
    if len(text) <= max_length:
        return [text]

    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break

        # Find last newline before limit
        split_pos = text.rfind('\n', 0, max_length)
        if split_pos == -1:
            split_pos = max_length

        chunks.append(text[:split_pos])
        text = text[split_pos:].lstrip()

    return chunks
```

---

## Media Handling

### Sending Photos

```python
from aiogram.types import FSInputFile, BufferedInputFile

# From file path
photo = FSInputFile("path/to/photo.jpg")
await message.answer_photo(photo, caption="Описание")

# From bytes (generated image)
photo_bytes = await generate_image()
photo = BufferedInputFile(photo_bytes, filename="image.png")
await message.answer_photo(photo, caption="Сгенерировано")

# From URL (not recommended, upload first)
# Telegram will download from URL - may be slow or fail
await message.answer_photo(photo="https://example.com/image.jpg")
```

### Media Groups

```python
from aiogram.types import InputMediaPhoto

async def send_media_group(chat_id: int, image_urls: list[str]):
    """Send multiple photos as album."""
    media = [
        InputMediaPhoto(media=url, caption="Фото" if i == 0 else None)
        for i, url in enumerate(image_urls)
    ]

    await bot.send_media_group(chat_id, media)
```

---

## Telegram Mini Apps

### WebApp Integration

```python
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    WebAppInfo
)

def get_webapp_keyboard(url: str) -> InlineKeyboardMarkup:
    """Create keyboard with WebApp button."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(
            text="🚀 Открыть приложение",
            web_app=WebAppInfo(url=url)
        )]
    ])

@router.message(Command("app"))
async def cmd_app(message: Message):
    """Open Mini App."""
    webapp_url = f"https://example.com/miniapp?user_id={message.from_user.id}"

    await message.answer(
        "Нажмите кнопку чтобы открыть приложение:",
        reply_markup=get_webapp_keyboard(webapp_url)
    )
```

### Validating WebApp Data

**MUST validate all data from WebApp:**

```python
import hashlib
import hmac
from urllib.parse import parse_qsl

def validate_webapp_data(init_data: str, bot_token: str) -> bool:
    """Validate Telegram WebApp initData."""
    try:
        parsed_data = dict(parse_qsl(init_data))
        hash_value = parsed_data.pop('hash', None)

        if not hash_value:
            return False

        # Create data check string
        data_check_arr = [f"{k}={v}" for k, v in sorted(parsed_data.items())]
        data_check_string = '\n'.join(data_check_arr)

        # Calculate hash
        secret_key = hmac.new(
            "WebAppData".encode(),
            bot_token.encode(),
            hashlib.sha256
        ).digest()

        calculated_hash = hmac.new(
            secret_key,
            data_check_string.encode(),
            hashlib.sha256
        ).hexdigest()

        return calculated_hash == hash_value

    except Exception:
        return False
```

---

## Webhooks vs Polling

### Polling (Development)

```python
# main.py
async def main():
    bot = Bot(token=settings.bot_token)
    dp = Dispatcher()

    # Start polling
    await dp.start_polling(
        bot,
        allowed_updates=dp.resolve_used_update_types()
    )
```

### Webhooks (Production)

```python
# main.py
from aiohttp import web

async def on_startup(app: web.Application):
    """Set webhook on startup."""
    bot: Bot = app['bot']
    webhook_url = f"{settings.webhook_url}/webhook"

    await bot.set_webhook(
        url=webhook_url,
        allowed_updates=dp.resolve_used_update_types(),
        drop_pending_updates=True
    )

async def on_shutdown(app: web.Application):
    """Delete webhook on shutdown."""
    bot: Bot = app['bot']
    await bot.delete_webhook()

async def webhook_handler(request: web.Request):
    """Handle incoming webhook updates."""
    bot: Bot = request.app['bot']
    dp: Dispatcher = request.app['dp']

    update = await request.json()
    telegram_update = Update(**update)

    await dp.feed_update(bot, telegram_update)
    return web.Response()

# Setup application
app = web.Application()
app['bot'] = bot
app['dp'] = dp
app.on_startup.append(on_startup)
app.on_shutdown.append(on_shutdown)
app.router.add_post('/webhook', webhook_handler)

web.run_app(app, host='0.0.0.0', port=8080)
```

**Webhook Requirements:**
- HTTPS with valid SSL certificate
- Public IP or domain
- Port 443, 80, 88, or 8443
- Fast response (< 1 second)

---

## Deep Links

### Creating Deep Links

```python
def create_start_link(bot_username: str, payload: str) -> str:
    """Create bot start deep link."""
    return f"https://t.me/{bot_username}?start={payload}"

# Example usage
referral_link = create_start_link("mybot", f"ref_{user_id}")
# https://t.me/mybot?start=ref_12345
```

### Handling Deep Links

```python
from aiogram.filters import CommandStart, CommandObject

@router.message(CommandStart(deep_link=True))
async def cmd_start_with_payload(
    message: Message,
    command: CommandObject
):
    """Handle /start with deep link payload."""
    payload = command.args  # e.g., "ref_12345"

    if payload.startswith("ref_"):
        referrer_id = payload[4:]
        await process_referral(message.from_user.id, referrer_id)

    await message.answer("Добро пожаловать!")
```

---

## Inline Mode

### Inline Query Handler

```python
from aiogram.types import (
    InlineQuery,
    InlineQueryResultArticle,
    InputTextMessageContent
)

@router.inline_query()
async def inline_search(inline_query: InlineQuery):
    """Handle inline queries."""
    query = inline_query.query

    # Search results
    results = await search_service.search(query)

    # Build response
    items = [
        InlineQueryResultArticle(
            id=str(item.id),
            title=item.title,
            description=item.description,
            input_message_content=InputTextMessageContent(
                message_text=item.content
            )
        )
        for item in results[:50]  # Max 50 results
    ]

    await inline_query.answer(
        items,
        cache_time=300,  # Cache for 5 minutes
        is_personal=True
    )
```

---

## User Privacy

### Data Collection

**MUST comply with Telegram privacy guidelines:**

```python
# services/user_service.py
async def register_user(user_id: int, username: str | None = None):
    """Register user (minimal data)."""
    # Store only necessary data
    user = User(
        user_id=user_id,
        username=username,  # Optional, can be None
        created_at=datetime.utcnow()
    )

    # DON'T store sensitive data:
    # - Phone numbers (unless explicitly shared)
    # - Full chat history
    # - Location data (without consent)

    await user_repository.create(user)
```

### User Deletion

```python
@router.message(Command("deletedata"))
async def cmd_delete_data(message: Message, user_service: UserService):
    """Handle user data deletion request."""
    await user_service.delete_user_data(message.from_user.id)
    await message.answer(
        "Ваши данные удалены в соответствии с политикой конфиденциальности."
    )
```

---

## Channel/Group Management

### Detecting Chat Type

```python
from aiogram.types import Message
from aiogram.enums import ChatType

@router.message()
async def handle_message(message: Message):
    """Handle message based on chat type."""
    if message.chat.type == ChatType.PRIVATE:
        # Private chat with user
        await handle_private_message(message)

    elif message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        # Group or supergroup
        await handle_group_message(message)

    elif message.chat.type == ChatType.CHANNEL:
        # Channel post
        await handle_channel_post(message)
```

### Admin Permissions

```python
from aiogram.types import ChatMemberAdministrator, ChatMemberOwner

async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    """Check if user is admin in chat."""
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return isinstance(member, (ChatMemberAdministrator, ChatMemberOwner))
    except Exception:
        return False

@router.message(Command("admin_command"))
async def cmd_admin(message: Message):
    """Admin-only command."""
    if not await is_admin(message.bot, message.chat.id, message.from_user.id):
        await message.answer("Эта команда доступна только администраторам.")
        return

    # Admin logic here
    await message.answer("Команда выполнена.")
```

---

## Best Practices

### DO

- ✅ Validate all data from Telegram (especially WebApp data)
- ✅ Respect rate limits (use semaphores/queues)
- ✅ Handle errors gracefully (bot blocks, API errors)
- ✅ Use webhooks in production (not polling)
- ✅ Split long messages to respect limits
- ✅ Acknowledge callback queries immediately
- ✅ Use structured logging for all user interactions
- ✅ Implement user data deletion on request

### DON'T

- ❌ Ignore rate limits (causes throttling)
- ❌ Trust WebApp data without validation
- ❌ Store unnecessary user data (privacy violation)
- ❌ Use polling in production (inefficient)
- ❌ Send messages > 4096 characters
- ❌ Ignore callback queries (causes loading spinner)
- ❌ Hardcode bot tokens (use environment variables)
- ❌ Block async handlers with sync operations

---

## Testing with Telegram

### Test Environment

Use Telegram Test DC for testing:

```python
# Test bot configuration
TEST_DC_URL = "https://api.telegram.org/bot{token}/test/"

# Create test bot
test_bot = Bot(
    token=test_token,
    server=TEST_DC_URL
)
```

### Mock for Unit Tests

```python
# tests/conftest.py
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def bot_mock():
    """Mock Telegram bot."""
    bot = AsyncMock()
    bot.send_message = AsyncMock(return_value=True)
    return bot

# tests/test_handlers.py
async def test_start_command(bot_mock, message_mock):
    """Test /start handler."""
    await cmd_start(message_mock)
    bot_mock.send_message.assert_called_once()
```

---

## References

- [Telegram Bot API Documentation](https://core.telegram.org/bots/api)
- [Telegram Mini Apps Documentation](https://core.telegram.org/bots/webapps)
- [Bot API Rate Limits](https://core.telegram.org/bots/faq#my-bot-is-hitting-limits-how-do-i-avoid-this)
- Framework standards: `.claude/standards/aiogram.md`
