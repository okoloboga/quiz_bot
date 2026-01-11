# Aiogram Standard

Production-ready patterns for building Telegram bots with aiogram 3.x.

## Core Principles

1. **Separation of Concerns**: Handlers → Services → Repositories
2. **No Business Logic in Handlers**: Handlers only route and validate
3. **FSM for Complex Dialogs**: Use Finite State Machines for multi-step conversations
4. **Structured Logging**: JSON logs for all bot interactions
5. **Environment Configuration**: No hardcoded tokens or secrets

---

## Project Structure

```
bot/
├── handlers/           # Command and callback handlers
│   ├── __init__.py
│   ├── start.py       # /start command
│   ├── common.py      # Common handlers (help, cancel)
│   └── feature.py     # Feature-specific handlers
├── services/          # Business logic layer
│   ├── __init__.py
│   ├── user_service.py
│   └── feature_service.py
├── repositories/      # Data access layer
│   ├── __init__.py
│   ├── user_repository.py
│   └── feature_repository.py
├── middlewares/       # Custom middleware
│   ├── __init__.py
│   ├── logging.py
│   └── auth.py
├── states/            # FSM state definitions
│   ├── __init__.py
│   └── feature_states.py
├── keyboards/         # Keyboard builders
│   ├── __init__.py
│   ├── inline.py
│   └── reply.py
├── filters/           # Custom filters
│   └── __init__.py
├── config.py          # Configuration from environment
└── main.py            # Bot entry point
```

---

## Configuration

**MUST** use environment variables for all secrets and configuration.

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    bot_token: str
    webhook_url: str | None = None
    redis_url: str = "redis://localhost:6379"
    postgres_dsn: str

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"

settings = Settings()
```

**.env.example** (committed to git):
```
BOT_TOKEN=your_bot_token_here
POSTGRES_DSN=postgresql+asyncpg://user:pass@db:5432/botdb
REDIS_URL=redis://redis:6379/0
WEBHOOK_URL=https://example.com/webhook
```

---

## Handlers

### Command Handlers

**Pattern**: Handlers MUST only validate input and delegate to services.

```python
# handlers/start.py
from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import Message
from services.user_service import UserService
import structlog

router = Router()
logger = structlog.get_logger()

@router.message(CommandStart())
async def cmd_start(message: Message, user_service: UserService):
    """Handle /start command."""
    logger.info("start_command", user_id=message.from_user.id)

    # Delegate to service layer
    user = await user_service.register_or_get_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        full_name=message.from_user.full_name
    )

    await message.answer(
        f"Привет, {user.full_name}! Добро пожаловать."
    )
```

### Callback Query Handlers

```python
# handlers/feature.py
from aiogram import Router, F
from aiogram.types import CallbackQuery

router = Router()

@router.callback_query(F.data == "confirm_action")
async def callback_confirm(callback: CallbackQuery, feature_service: FeatureService):
    """Handle confirmation callback."""
    await callback.answer()  # Always acknowledge callback

    result = await feature_service.process_confirmation(
        user_id=callback.from_user.id
    )

    await callback.message.edit_text(f"Подтверждено: {result}")
```

---

## Finite State Machine (FSM)

**MUST** use FSM for multi-step conversations.

### State Definition

```python
# states/registration.py
from aiogram.fsm.state import State, StatesGroup

class RegistrationStates(StatesGroup):
    waiting_for_name = State()
    waiting_for_email = State()
    waiting_for_confirmation = State()
```

### FSM Handlers

```python
# handlers/registration.py
from aiogram import Router
from aiogram.fsm.context import FSMContext
from aiogram.types import Message
from states.registration import RegistrationStates

router = Router()

@router.message(Command("register"))
async def start_registration(message: Message, state: FSMContext):
    """Start registration flow."""
    await state.set_state(RegistrationStates.waiting_for_name)
    await message.answer("Как вас зовут?")

@router.message(RegistrationStates.waiting_for_name)
async def process_name(message: Message, state: FSMContext):
    """Process name input."""
    await state.update_data(name=message.text)
    await state.set_state(RegistrationStates.waiting_for_email)
    await message.answer("Введите ваш email:")

@router.message(RegistrationStates.waiting_for_email)
async def process_email(message: Message, state: FSMContext, user_service: UserService):
    """Process email and complete registration."""
    data = await state.get_data()

    # Delegate to service
    await user_service.complete_registration(
        user_id=message.from_user.id,
        name=data["name"],
        email=message.text
    )

    await state.clear()
    await message.answer("Регистрация завершена!")
```

---

## Keyboards

### Inline Keyboards

```python
# keyboards/inline.py
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton

def get_confirmation_keyboard() -> InlineKeyboardMarkup:
    """Build confirmation keyboard."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Да", callback_data="confirm_yes"),
            InlineKeyboardButton(text="❌ Нет", callback_data="confirm_no")
        ]
    ])
```

### Reply Keyboards

```python
# keyboards/reply.py
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton

def get_main_menu_keyboard() -> ReplyKeyboardMarkup:
    """Build main menu keyboard."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Меню")],
            [KeyboardButton(text="⚙️ Настройки"), KeyboardButton(text="ℹ️ Помощь")]
        ],
        resize_keyboard=True
    )
```

---

## Middleware

### Logging Middleware

**MUST** log all incoming updates with structured logging.

```python
# middlewares/logging.py
from aiogram import BaseMiddleware
from aiogram.types import Update
import structlog

class LoggingMiddleware(BaseMiddleware):
    """Log all incoming updates."""

    async def __call__(self, handler, event: Update, data: dict):
        logger = structlog.get_logger()

        logger.info(
            "update_received",
            update_id=event.update_id,
            user_id=event.event.from_user.id if event.event else None,
            update_type=event.event_type
        )

        try:
            result = await handler(event, data)
            logger.info("update_processed", update_id=event.update_id)
            return result
        except Exception as e:
            logger.error(
                "update_failed",
                update_id=event.update_id,
                error=str(e),
                exc_info=True
            )
            raise
```

### Dependency Injection Middleware

```python
# middlewares/services.py
from aiogram import BaseMiddleware
from services.user_service import UserService
from repositories.user_repository import UserRepository

class ServiceMiddleware(BaseMiddleware):
    """Inject services into handlers."""

    def __init__(self, session_pool):
        self.session_pool = session_pool

    async def __call__(self, handler, event, data: dict):
        async with self.session_pool() as session:
            # Inject repositories
            user_repo = UserRepository(session)

            # Inject services
            data["user_service"] = UserService(user_repo)

            return await handler(event, data)
```

---

## Error Handling

**MUST** handle errors gracefully and log them.

```python
# handlers/errors.py
from aiogram import Router
from aiogram.types import ErrorEvent
import structlog

router = Router()
logger = structlog.get_logger()

@router.errors()
async def error_handler(event: ErrorEvent):
    """Global error handler."""
    logger.error(
        "handler_error",
        update_id=event.update.update_id,
        error=str(event.exception),
        exc_info=event.exception
    )

    # Notify user
    if event.update.message:
        await event.update.message.answer(
            "Произошла ошибка. Попробуйте позже."
        )
```

---

## Main Application

```python
# main.py
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.redis import RedisStorage
from config import settings
from handlers import start, feature, errors
from middlewares.logging import LoggingMiddleware
from middlewares.services import ServiceMiddleware
import structlog

async def main():
    """Start the bot."""
    # Configure structured logging
    structlog.configure(
        processors=[
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer()
        ]
    )

    logger = structlog.get_logger()
    logger.info("bot_starting")

    # Initialize bot and dispatcher
    bot = Bot(token=settings.bot_token)
    storage = RedisStorage.from_url(settings.redis_url)
    dp = Dispatcher(storage=storage)

    # Register middleware
    dp.update.middleware(LoggingMiddleware())
    dp.update.middleware(ServiceMiddleware(session_pool))

    # Register routers
    dp.include_router(errors.router)
    dp.include_router(start.router)
    dp.include_router(feature.router)

    # Start polling
    await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())

if __name__ == "__main__":
    asyncio.run(main())
```

---

## Best Practices

### DO

- ✅ Use FSM for multi-step conversations
- ✅ Always acknowledge callback queries with `callback.answer()`
- ✅ Use dependency injection for services
- ✅ Log all user interactions with structured logs
- ✅ Validate user input in handlers, process in services
- ✅ Use Redis for FSM storage in production
- ✅ Handle errors gracefully and notify users
- ✅ Use environment variables for configuration

### DON'T

- ❌ Put business logic in handlers
- ❌ Hardcode bot tokens or secrets
- ❌ Ignore callback queries (causes loading spinner)
- ❌ Use blocking I/O operations (always async)
- ❌ Store sensitive data in FSM state (use database)
- ❌ Skip error handling
- ❌ Use MemoryStorage in production (use Redis)

---

## Testing

```python
# tests/test_handlers.py
import pytest
from aiogram.methods import SendMessage
from aiogram.fsm.context import FSMContext
from handlers.start import cmd_start

@pytest.mark.asyncio
async def test_start_command(bot, message_from_user, user_service_mock):
    """Test /start command."""
    message = message_from_user(text="/start")

    await cmd_start(message, user_service=user_service_mock)

    # Verify service was called
    user_service_mock.register_or_get_user.assert_called_once()

    # Verify response
    assert message.answer.called
```

---

## References

- [aiogram 3.x Documentation](https://docs.aiogram.dev/en/latest/)
- [Telegram Bot API](https://core.telegram.org/bots/api)
- Framework standards: `.claude/standards/docker.md`, `.claude/standards/testing.md`
