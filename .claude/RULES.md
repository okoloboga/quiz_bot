# Shared Rules

All agents and commands inherit these rules. Don't repeat them elsewhere.

## Process
- Flow: `/discovery` → `/plan` → `/implement` → `/test` → `/review` → `/ship`
- No code without approved `/plan`
- No architecture changes during `/implement`

## Code
- Type hints required
- Handlers → Services → Repositories (no business logic in handlers)
- Environment variables only (no hardcoded secrets)
- Structured JSON logging
- Tests: >80% coverage

## AI Features
- Prompts versioned (no magic strings)
- Retry with exponential backoff
- Fallback behavior defined
- Log: model, tokens, cost, latency

## Docker
- All code must work in `docker-compose`
- Validate cold start before shipping
- Health checks required

## Quality Gates

| Gate | Authority | Blocks If |
|------|-----------|-----------|
| Plan | Tech Lead | Architecture unclear or violates standards |
| Test | QA | Acceptance criteria not met |
| Review | Reviewer | Code quality or security issues |
| Ship | Tech Lead + DevOps | Docker fails or secrets hardcoded |

## Standards
See `standards/` for: aiogram, docker, telegram, rag, testing
