# Development Process

**Workflow**: See `README.md`

## Quality Gates

| Gate | Owner | Blocks If |
|------|-------|-----------|
| Plan | Tech Lead | Architecture unclear or violates standards |
| Test | QA | Acceptance criteria not met |
| Review | Reviewer | Code quality or security issues |
| Ship | Tech Lead + DevOps | Docker fails, secrets hardcoded |

## Definition of Done

- [ ] Works in docker-compose (cold start)
- [ ] No hardcoded secrets
- [ ] Tests pass (>80% coverage)
- [ ] QA + Reviewer + Tech Lead approved
- [ ] AI prompts versioned (if applicable)
- [ ] Structured JSON logging

## Invariants

1. No code without `/plan` approval
2. No shipping without `/test` + `/review`
3. Docker cold start must work
4. AI prompts versioned (no magic strings)
5. Handlers → Services → Repositories
