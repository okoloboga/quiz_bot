# Testing Standard

Test-Driven Development patterns for Telegram bots, AI systems, and backend services.

## Core Principles

1. **Write Tests First**: TDD approach - test before implementation
2. **Test Pyramid**: More unit tests, fewer integration tests, minimal E2E
3. **Test in Docker**: All tests must run in docker-compose environment
4. **Mock External APIs**: Never call real APIs in tests
5. **Coverage Threshold**: Minimum 80% code coverage
6. **Fast Feedback**: Tests should run in < 30 seconds

---

## Test Structure

```
tests/
├── unit/                    # Fast, isolated unit tests
│   ├── test_services.py
│   ├── test_repositories.py
│   └── test_utils.py
├── integration/             # Tests with real database
│   ├── test_api_endpoints.py
│   ├── test_bot_handlers.py
│   └── test_celery_tasks.py
├── e2e/                     # End-to-end tests
│   └── test_user_flows.py
├── fixtures/                # Test data and fixtures
│   ├── __init__.py
│   ├── telegram_fixtures.py
│   └── database_fixtures.py
└── conftest.py             # Pytest configuration and shared fixtures
```

---

## Unit Tests

### Service Layer Tests

```python
# tests/unit/test_user_service.py
import pytest
from unittest.mock import AsyncMock, Mock
from services.user_service import UserService
from models.user import User

@pytest.fixture
def user_repository_mock():
    """Mock user repository."""
    repo = AsyncMock()
    repo.get_by_id = AsyncMock()
    repo.create = AsyncMock()
    return repo

@pytest.fixture
def user_service(user_repository_mock):
    """Create user service with mocked repository."""
    return UserService(user_repository=user_repository_mock)

@pytest.mark.asyncio
async def test_register_user_success(user_service, user_repository_mock):
    """Test successful user registration."""
    # Arrange
    user_id = 12345
    username = "testuser"
    expected_user = User(user_id=user_id, username=username)

    user_repository_mock.get_by_id.return_value = None  # User doesn't exist
    user_repository_mock.create.return_value = expected_user

    # Act
    result = await user_service.register_or_get_user(user_id, username)

    # Assert
    assert result.user_id == user_id
    assert result.username == username
    user_repository_mock.create.assert_called_once()

@pytest.mark.asyncio
async def test_register_user_already_exists(user_service, user_repository_mock):
    """Test registration when user already exists."""
    # Arrange
    existing_user = User(user_id=12345, username="existing")
    user_repository_mock.get_by_id.return_value = existing_user

    # Act
    result = await user_service.register_or_get_user(12345, "newname")

    # Assert
    assert result == existing_user
    user_repository_mock.create.assert_not_called()
```

---

## Integration Tests

### Database Tests

```python
# tests/integration/test_user_repository.py
import pytest
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from repositories.user_repository import UserRepository
from models.user import User, Base

@pytest.fixture
async def test_db():
    """Create test database."""
    engine = create_async_engine(
        "postgresql+asyncpg://test:test@postgres_test:5432/test_db",
        echo=True
    )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    yield async_session

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.mark.asyncio
async def test_create_user(test_db):
    """Test creating a user in database."""
    async with test_db() as session:
        repo = UserRepository(session)

        # Create user
        user = await repo.create(
            user_id=12345,
            username="testuser",
            full_name="Test User"
        )

        # Verify
        assert user.user_id == 12345
        assert user.username == "testuser"

        # Verify in database
        fetched = await repo.get_by_id(12345)
        assert fetched is not None
        assert fetched.username == "testuser"
```

---

## Telegram Bot Tests

### Handler Tests

```python
# tests/unit/test_handlers.py
import pytest
from unittest.mock import AsyncMock, Mock
from aiogram import types
from handlers.start import cmd_start

@pytest.fixture
def message_mock():
    """Mock Telegram message."""
    message = Mock(spec=types.Message)
    message.from_user = Mock()
    message.from_user.id = 12345
    message.from_user.username = "testuser"
    message.from_user.full_name = "Test User"
    message.answer = AsyncMock()
    return message

@pytest.fixture
def user_service_mock():
    """Mock user service."""
    service = AsyncMock()
    service.register_or_get_user = AsyncMock()
    return service

@pytest.mark.asyncio
async def test_start_command(message_mock, user_service_mock):
    """Test /start command handler."""
    # Arrange
    user_service_mock.register_or_get_user.return_value = Mock(
        full_name="Test User"
    )

    # Act
    await cmd_start(message_mock, user_service=user_service_mock)

    # Assert
    user_service_mock.register_or_get_user.assert_called_once_with(
        user_id=12345,
        username="testuser",
        full_name="Test User"
    )
    message_mock.answer.assert_called_once()
    assert "Привет" in message_mock.answer.call_args[0][0]
```

### FSM Tests

```python
# tests/integration/test_fsm.py
import pytest
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from states.registration import RegistrationStates
from handlers.registration import process_name, process_email

@pytest.fixture
async def fsm_context():
    """Create FSM context for testing."""
    storage = MemoryStorage()
    context = FSMContext(
        storage=storage,
        key={"chat_id": 12345, "user_id": 12345}
    )
    yield context
    await storage.close()

@pytest.mark.asyncio
async def test_registration_flow(message_mock, fsm_context, user_service_mock):
    """Test complete registration FSM flow."""
    # Step 1: Enter name
    await fsm_context.set_state(RegistrationStates.waiting_for_name)
    message_mock.text = "John Doe"
    await process_name(message_mock, state=fsm_context)

    # Verify state transition
    assert await fsm_context.get_state() == RegistrationStates.waiting_for_email

    # Verify data saved
    data = await fsm_context.get_data()
    assert data["name"] == "John Doe"

    # Step 2: Enter email
    message_mock.text = "john@example.com"
    await process_email(message_mock, state=fsm_context, user_service=user_service_mock)

    # Verify completion
    assert await fsm_context.get_state() is None  # State cleared
    user_service_mock.complete_registration.assert_called_once()
```

---

## AI/RAG Tests

### LLM Mocking

```python
# tests/unit/test_rag_service.py
import pytest
from unittest.mock import AsyncMock, Mock
from services.rag_service import RAGService

@pytest.fixture
def openai_mock(monkeypatch):
    """Mock OpenAI client."""
    mock_client = AsyncMock()

    # Mock embeddings
    mock_client.embeddings.create = AsyncMock(return_value=Mock(
        data=[Mock(embedding=[0.1, 0.2, 0.3])],
        usage=Mock(total_tokens=10)
    ))

    # Mock chat completions
    mock_client.chat.completions.create = AsyncMock(return_value=Mock(
        choices=[Mock(message=Mock(content="Mocked answer"))],
        usage=Mock(prompt_tokens=100, completion_tokens=50, total_tokens=150)
    ))

    return mock_client

@pytest.mark.asyncio
async def test_rag_generation(openai_mock):
    """Test RAG answer generation."""
    # Arrange
    retrieval_mock = AsyncMock()
    retrieval_mock.retrieve.return_value = [
        {"text": "Context 1", "metadata": {}, "final_score": 0.9}
    ]

    rag_service = RAGService(
        retrieval_service=retrieval_mock,
        openai_api_key="test_key"
    )
    rag_service.client = openai_mock

    # Act
    result = await rag_service.generate_answer("Test question")

    # Assert
    assert result["answer"] == "Mocked answer"
    assert len(result["sources"]) == 1
    retrieval_mock.retrieve.assert_called_once()
    openai_mock.chat.completions.create.assert_called_once()
```

---

## API Tests (FastAPI)

### Endpoint Tests

```python
# tests/integration/test_api.py
import pytest
from httpx import AsyncClient
from main import app

@pytest.fixture
async def async_client():
    """Create async HTTP client."""
    async with AsyncClient(app=app, base_url="http://test") as client:
        yield client

@pytest.mark.asyncio
async def test_health_endpoint(async_client):
    """Test /health endpoint."""
    response = await async_client.get("/health")

    assert response.status_code == 200
    assert response.json()["status"] == "healthy"

@pytest.mark.asyncio
async def test_create_user_endpoint(async_client):
    """Test POST /users endpoint."""
    payload = {
        "user_id": 12345,
        "username": "testuser"
    }

    response = await async_client.post("/users", json=payload)

    assert response.status_code == 201
    data = response.json()
    assert data["user_id"] == 12345
    assert data["username"] == "testuser"
```

---

## Celery Tests

### Task Tests

```python
# tests/unit/test_celery_tasks.py
import pytest
from unittest.mock import AsyncMock, patch
from celery_app.tasks import generate_digest_task

@pytest.mark.asyncio
async def test_generate_digest_task():
    """Test digest generation task."""
    with patch('celery_app.tasks.DigestService') as mock_service:
        # Arrange
        mock_instance = AsyncMock()
        mock_service.return_value = mock_instance
        mock_instance.generate_digest.return_value = {
            "title": "Test Digest",
            "content": "Summary"
        }

        # Act
        result = await generate_digest_task.apply_async(
            args=[12345, ["channel1", "channel2"]]
        ).get()

        # Assert
        assert result["title"] == "Test Digest"
        mock_instance.generate_digest.assert_called_once()
```

---

## Test Configuration

### conftest.py

```python
# tests/conftest.py
import pytest
import asyncio
from typing import Generator

# Configure async event loop
@pytest.fixture(scope="session")
def event_loop() -> Generator:
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

# Shared fixtures
@pytest.fixture
def bot_token() -> str:
    """Test bot token."""
    return "123456:TEST_TOKEN"

@pytest.fixture
async def redis_client():
    """Redis client for tests."""
    import redis.asyncio as redis
    client = redis.from_url("redis://redis_test:6379/0")
    yield client
    await client.flushdb()
    await client.close()
```

---

## pytest.ini

```ini
[pytest]
asyncio_mode = auto
testpaths = tests
python_files = test_*.py
python_classes = Test*
python_functions = test_*
addopts =
    -v
    --strict-markers
    --cov=.
    --cov-report=term-missing
    --cov-report=html
    --cov-fail-under=80
markers =
    unit: Unit tests (fast, no external dependencies)
    integration: Integration tests (database, redis)
    e2e: End-to-end tests (slow)
```

---

## Running Tests

### In Docker Compose

```yaml
# docker-compose.test.yml
version: '3.9'

services:
  test_runner:
    build:
      context: .
      dockerfile: Dockerfile.test
    depends_on:
      postgres_test:
        condition: service_healthy
      redis_test:
        condition: service_healthy
    environment:
      - POSTGRES_DSN=postgresql+asyncpg://test:test@postgres_test:5432/test_db
      - REDIS_URL=redis://redis_test:6379/0
    command: pytest tests/ -v --cov=.

  postgres_test:
    image: postgres:15-alpine
    environment:
      POSTGRES_USER: test
      POSTGRES_PASSWORD: test
      POSTGRES_DB: test_db
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U test -d test_db"]
      interval: 5s
      timeout: 5s
      retries: 5

  redis_test:
    image: redis:7-alpine
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 5s
      retries: 5
```

**Run tests:**
```bash
docker-compose -f docker-compose.test.yml up --abort-on-container-exit
```

---

## Coverage

### Generating Coverage Reports

```bash
# Run tests with coverage
pytest --cov=. --cov-report=html --cov-report=term

# View HTML report
open htmlcov/index.html
```

### Coverage Thresholds

**MUST meet minimum coverage:**
- Overall: 80%
- Services: 90%
- Handlers: 85%
- Repositories: 90%

```python
# .coveragerc
[run]
source = .
omit =
    tests/*
    venv/*
    */migrations/*

[report]
exclude_lines =
    pragma: no cover
    def __repr__
    raise AssertionError
    raise NotImplementedError
    if __name__ == .__main__.:
```

---

## Best Practices

### DO

- ✅ Write tests before implementation (TDD)
- ✅ Use descriptive test names (test_what_when_then)
- ✅ Mock external APIs (Telegram, OpenAI, etc.)
- ✅ Test both success and error paths
- ✅ Run tests in docker-compose
- ✅ Maintain > 80% code coverage
- ✅ Use fixtures for shared setup
- ✅ Test edge cases and boundaries

### DON'T

- ❌ Call real APIs in tests
- ❌ Use production database for tests
- ❌ Write tests after implementation
- ❌ Skip error case tests
- ❌ Hardcode test data (use fixtures)
- ❌ Share state between tests
- ❌ Write slow tests (optimize or mark as e2e)
- ❌ Ignore failing tests

---

## CI/CD Integration

### GitHub Actions Example

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  test:
    runs-on: ubuntu-latest

    steps:
      - uses: actions/checkout@v3

      - name: Run tests
        run: |
          docker-compose -f docker-compose.test.yml up --abort-on-container-exit

      - name: Upload coverage
        uses: codecov/codecov-action@v3
        with:
          files: ./coverage.xml
```

---

## Fixtures Library

### Common Fixtures

```python
# tests/fixtures/telegram_fixtures.py
from unittest.mock import Mock
from aiogram import types

def create_message_mock(
    user_id: int = 12345,
    username: str = "testuser",
    text: str = "test message"
) -> Mock:
    """Create mock Telegram message."""
    message = Mock(spec=types.Message)
    message.from_user = Mock()
    message.from_user.id = user_id
    message.from_user.username = username
    message.text = text
    message.answer = Mock(return_value=None)
    return message

def create_callback_query_mock(
    user_id: int = 12345,
    data: str = "callback_data"
) -> Mock:
    """Create mock callback query."""
    callback = Mock(spec=types.CallbackQuery)
    callback.from_user = Mock()
    callback.from_user.id = user_id
    callback.data = data
    callback.answer = Mock(return_value=None)
    callback.message = create_message_mock()
    return callback
```

---

## References

- [pytest Documentation](https://docs.pytest.org/)
- [pytest-asyncio](https://pytest-asyncio.readthedocs.io/)
- [Coverage.py](https://coverage.readthedocs.io/)
- Framework standards: `.claude/standards/aiogram.md`, `.claude/standards/docker.md`
