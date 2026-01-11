# Docker Standard

Production-ready patterns for docker-compose based infrastructure. Docker is the **source of truth** for runtime.

## Core Principles

1. **Zero Manual Setup**: `docker-compose up` must work from scratch
2. **No Hardcoded Values**: All configuration via environment variables
3. **Health Checks**: Every service must have health checks
4. **Proper Dependencies**: Use `depends_on` with health conditions
5. **Volume Management**: Persistent data in named volumes
6. **Network Isolation**: Use custom networks for service communication

---

## Project Structure

```
project/
├── docker-compose.yml       # Main compose file
├── docker-compose.dev.yml   # Development overrides (optional)
├── .env.example            # Template with documentation
├── .env                    # Actual values (gitignored)
├── Dockerfile              # Application image
├── services/               # Service-specific Dockerfiles
│   ├── bot/Dockerfile
│   ├── backend/Dockerfile
│   └── worker/Dockerfile
└── scripts/
    ├── wait-for-it.sh     # Wait for service availability
    └── init-db.sh         # Database initialization
```

---

## docker-compose.yml Structure

### Complete Example

```yaml
version: '3.9'

services:
  # PostgreSQL Database
  postgres:
    image: postgres:15-alpine
    container_name: app_postgres
    restart: unless-stopped
    environment:
      POSTGRES_USER: ${POSTGRES_USER}
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: ${POSTGRES_DB}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./scripts/init-db.sh:/docker-entrypoint-initdb.d/init-db.sh
    ports:
      - "${POSTGRES_PORT:-5432}:5432"
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - app_network

  # Redis Cache
  redis:
    image: redis:7-alpine
    container_name: app_redis
    restart: unless-stopped
    command: redis-server --requirepass ${REDIS_PASSWORD}
    volumes:
      - redis_data:/data
    ports:
      - "${REDIS_PORT:-6379}:6379"
    healthcheck:
      test: ["CMD", "redis-cli", "--raw", "incr", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
    networks:
      - app_network

  # Telegram Bot Service
  bot:
    build:
      context: .
      dockerfile: services/bot/Dockerfile
    container_name: app_bot
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - BOT_TOKEN=${BOT_TOKEN}
      - POSTGRES_DSN=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "python -c 'import asyncio; asyncio.run(ping())'"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - app_network

  # FastAPI Backend
  backend:
    build:
      context: .
      dockerfile: services/backend/Dockerfile
    container_name: app_backend
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - POSTGRES_DSN=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
    ports:
      - "${BACKEND_PORT:-8000}:8000"
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
      interval: 30s
      timeout: 10s
      retries: 3
    networks:
      - app_network

  # Celery Worker
  worker:
    build:
      context: .
      dockerfile: services/worker/Dockerfile
    container_name: app_worker
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - POSTGRES_DSN=postgresql+asyncpg://${POSTGRES_USER}:${POSTGRES_PASSWORD}@postgres:5432/${POSTGRES_DB}
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/1
    command: celery -A app.worker worker --loglevel=info
    depends_on:
      postgres:
        condition: service_healthy
      redis:
        condition: service_healthy
    networks:
      - app_network

  # Celery Beat (Scheduler)
  beat:
    build:
      context: .
      dockerfile: services/worker/Dockerfile
    container_name: app_beat
    restart: unless-stopped
    env_file:
      - .env
    environment:
      - REDIS_URL=redis://:${REDIS_PASSWORD}@redis:6379/0
      - CELERY_BROKER_URL=redis://:${REDIS_PASSWORD}@redis:6379/1
    command: celery -A app.worker beat --loglevel=info
    depends_on:
      redis:
        condition: service_healthy
    networks:
      - app_network

volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local

networks:
  app_network:
    driver: bridge
```

---

## Dockerfile Best Practices

### Multi-Stage Build

```dockerfile
# services/bot/Dockerfile
FROM python:3.11-slim as builder

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Production stage
FROM python:3.11-slim

WORKDIR /app

# Copy dependencies from builder
COPY --from=builder /root/.local /root/.local
ENV PATH=/root/.local/bin:$PATH

# Copy application code
COPY bot/ ./bot/
COPY shared/ ./shared/

# Non-root user
RUN useradd -m -u 1000 botuser && chown -R botuser:botuser /app
USER botuser

# Health check script
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import sys; sys.exit(0)"

CMD ["python", "-m", "bot.main"]
```

---

## Environment Variables

### .env.example (MUST be committed)

```bash
# PostgreSQL Configuration
POSTGRES_USER=appuser
POSTGRES_PASSWORD=changeme
POSTGRES_DB=appdb
POSTGRES_PORT=5432

# Redis Configuration
REDIS_PASSWORD=changeme
REDIS_PORT=6379

# Telegram Bot
BOT_TOKEN=your_bot_token_here

# Backend API
BACKEND_PORT=8000
SECRET_KEY=your_secret_key_here

# AI Services
OPENAI_API_KEY=your_openai_key_here
COMET_API_KEY=your_comet_key_here

# Celery
CELERY_BROKER_URL=redis://:changeme@redis:6379/1
CELERY_RESULT_BACKEND=redis://:changeme@redis:6379/2

# Application Settings
LOG_LEVEL=INFO
DEBUG=false
```

### .env (gitignored, created from example)

```bash
# Copy .env.example to .env and fill with real values
# This file MUST be in .gitignore
```

---

## Health Checks

**Every service MUST have a health check.**

### Database Health Check

```yaml
healthcheck:
  test: ["CMD-SHELL", "pg_isready -U ${POSTGRES_USER} -d ${POSTGRES_DB}"]
  interval: 10s
  timeout: 5s
  retries: 5
  start_period: 10s
```

### HTTP Service Health Check

```yaml
healthcheck:
  test: ["CMD-SHELL", "curl -f http://localhost:8000/health || exit 1"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 40s
```

### Application Health Endpoint

```python
# backend/app/health.py
from fastapi import APIRouter
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

@router.get("/health")
async def health_check(db: AsyncSession):
    """Health check endpoint."""
    try:
        # Test database connection
        await db.execute("SELECT 1")
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        return {"status": "unhealthy", "error": str(e)}, 503
```

---

## Service Dependencies

**MUST use `depends_on` with health conditions.**

```yaml
bot:
  depends_on:
    postgres:
      condition: service_healthy  # Wait for DB to be healthy
    redis:
      condition: service_healthy  # Wait for Redis to be healthy
```

❌ **DON'T** (race conditions):
```yaml
bot:
  depends_on:
    - postgres  # Service started, but may not be ready
    - redis
```

---

## Volumes

### Named Volumes (Recommended)

```yaml
volumes:
  postgres_data:
    driver: local
  redis_data:
    driver: local

services:
  postgres:
    volumes:
      - postgres_data:/var/lib/postgresql/data
```

### Bind Mounts (Development Only)

```yaml
# docker-compose.dev.yml
services:
  bot:
    volumes:
      - ./bot:/app/bot:ro  # Mount source code for hot reload
```

---

## Networks

**MUST use custom networks** for service isolation.

```yaml
networks:
  app_network:
    driver: bridge
  external_network:
    external: true

services:
  backend:
    networks:
      - app_network      # Internal communication
      - external_network # External APIs
```

---

## Database Migrations

### Using Alembic

```dockerfile
# services/backend/Dockerfile
# Add migration step
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
```

### Init Script

```bash
# scripts/init-db.sh
#!/bin/bash
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
    CREATE EXTENSION IF NOT EXISTS "pg_trgm";
EOSQL
```

---

## Development vs Production

### Base Configuration

`docker-compose.yml` - production-ready base

### Development Overrides

```yaml
# docker-compose.dev.yml
version: '3.9'

services:
  bot:
    build:
      target: development  # Use dev stage in Dockerfile
    volumes:
      - ./bot:/app/bot:ro  # Hot reload
    environment:
      - LOG_LEVEL=DEBUG
      - DEBUG=true

  backend:
    ports:
      - "8000:8000"
    volumes:
      - ./backend:/app/backend:ro
    command: uvicorn app.main:app --reload --host 0.0.0.0
```

**Usage**:
```bash
# Development
docker-compose -f docker-compose.yml -f docker-compose.dev.yml up

# Production
docker-compose up -d
```

---

## Common Commands

```bash
# Start all services
docker-compose up -d

# View logs
docker-compose logs -f [service_name]

# Restart specific service
docker-compose restart bot

# Execute command in running container
docker-compose exec bot python manage.py shell

# Stop and remove containers
docker-compose down

# Stop and remove containers + volumes
docker-compose down -v

# Rebuild specific service
docker-compose build --no-cache bot

# Check service health
docker-compose ps
```

---

## Best Practices

### DO

- ✅ Use named volumes for persistent data
- ✅ Implement health checks for all services
- ✅ Use `depends_on` with health conditions
- ✅ Document all environment variables in `.env.example`
- ✅ Use multi-stage builds to minimize image size
- ✅ Run containers as non-root users
- ✅ Use specific image tags (not `latest`)
- ✅ Test cold start regularly (`docker-compose down -v && docker-compose up`)

### DON'T

- ❌ Hardcode secrets or configuration
- ❌ Use `latest` tags in production
- ❌ Commit `.env` files to git
- ❌ Use `depends_on` without health conditions
- ❌ Run containers as root
- ❌ Store data in containers (use volumes)
- ❌ Expose unnecessary ports
- ❌ Skip health checks

---

## Validation Checklist

Before shipping, verify:

- [ ] `docker-compose down -v && docker-compose up` works from scratch
- [ ] All services have health checks
- [ ] `.env.example` documents all required variables
- [ ] `.env` is in `.gitignore`
- [ ] No hardcoded secrets in docker-compose.yml or Dockerfiles
- [ ] Logs are visible with `docker-compose logs`
- [ ] Services restart on failure (`restart: unless-stopped`)
- [ ] Database migrations run automatically
- [ ] Volumes are configured for persistent data

---

## References

- [Docker Compose Documentation](https://docs.docker.com/compose/)
- [Dockerfile Best Practices](https://docs.docker.com/develop/develop-images/dockerfile_best-practices/)
- Framework standards: `.claude/CLAUDE.md`
