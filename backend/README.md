# Backend

FastAPI backend for ELIN 神域引擎。

## Local Development
```bash
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Auth APIs (MVP progress)
- `POST /api/v1/auth/register`
  - creates user with hashed password
  - returns `verification_token` for dev flow
- `POST /api/v1/auth/login`
  - verifies email/password
  - returns HS256 bearer token with `email_verified` claim
- `POST /api/v1/auth/verify-email`
  - verifies token and flips `email_verified=true`

## Database
- Primary DB: PostgreSQL
- Default local URL: `postgresql+psycopg://postgres:postgres@localhost:5432/elin`
- Docker Compose URL (inside container): `postgresql+psycopg://postgres:postgres@postgres:5432/elin`

Environment variables:
- `DATABASE_URL`: app runtime database
- `TEST_DATABASE_URL`: test-only database (use `elin_test`)
- `JWT_SECRET`: HS256 signing secret for access token
- `JWT_ALGORITHM`: JWT algorithm (default `HS256`)
- `JWT_EXP_MINUTES`: access token expiration in minutes (default `60`)

## Migrations (Alembic)
Run on host:
```bash
uv run alembic upgrade head
```

Run in compose backend container:
```bash
docker compose exec backend uv run alembic upgrade head
```

Create a migration:
```bash
uv run alembic revision --autogenerate -m "message"
```

## Tests
Create test DB once:
```bash
docker compose exec postgres psql -U postgres -d postgres -c "CREATE DATABASE elin_test;"
```

Run tests:
```bash
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/elin_test uv run pytest -q
```

Safety note:
- `backend/tests/test_user_schema.py` is destructive for target tables.
- Never point `TEST_DATABASE_URL` to primary DB `elin`.

## Lint and Hooks
Run backend lint:
```bash
uv run ruff check .
```

Install and run pre-commit from backend environment:
```bash
uv run pre-commit install
uv run pre-commit run --all-files
```
