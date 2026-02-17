# ELIN 神域引擎 - Monorepo Bootstrap

This repository contains a minimal fullstack setup:
- Frontend: Next.js (App Router + TypeScript)
- Backend: FastAPI (Python, managed with `uv`)
- Containers: Docker Compose for local development

## Project Structure
- `frontend/`: Next.js app
- `backend/`: FastAPI app
- `docker-compose.yml`: local dev orchestration

## Run with Docker Compose
```bash
docker compose up --build
```

For background mode:
```bash
docker compose up -d --build
```

Services:
- Frontend: http://localhost:3000
- Backend health: http://localhost:8000/api/v1/health
- PostgreSQL: `localhost:5432` (db: `elin`, user: `postgres`, password: `postgres`)

## Rebuild/Restart Rules
Use this quick rule during development:

- Code-only changes in `frontend/app/**` or `backend/app/**`:
  usually no restart needed (Next.js dev + Uvicorn `--reload` handle hot reload).
- Changes to `docker-compose.yml` environment, `.env`, ports, volumes:
  run `docker compose up -d` (or `docker compose up -d --build` if unsure).
- Changes to Dockerfiles:
  run `docker compose up -d --build`.
- Changes to dependencies (`frontend/package.json`, `frontend/package-lock.json`, `backend/pyproject.toml`, `backend/uv.lock`):
  run `docker compose up -d --build` (recommended).

When to use `-d`:
- Use `-d` when you want services running in background and your terminal back immediately.
- Do not use `-d` when you want to watch startup/runtime logs interactively for debugging.

## API Endpoints
- `GET /api/v1/health`
- `POST /api/v1/auth/register`
- `POST /api/v1/auth/verify-email`
- `POST /api/v1/ask`

`POST /api/v1/ask` requires `Authorization: Bearer <token>`.
For current dev stage, token payload must include `email_verified` boolean.

Example:
```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"demo@example.com","password":"Password123"}'
```

```bash
curl -X POST http://localhost:8000/api/v1/auth/verify-email \
  -H "Content-Type: application/json" \
  -d '{"token":"<verification_token_from_register>"}'
```

```bash
curl -X POST http://localhost:8000/api/v1/ask \
  -H "Authorization: Bearer eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJlbWFpbF92ZXJpZmllZCI6dHJ1ZX0." \
  -H "Content-Type: application/json" \
  -d '{"question":"今天該聚焦什麼？","lang":"zh","mode":"analysis"}'
```

Dev tokens:
- verified: `eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJlbWFpbF92ZXJpZmllZCI6dHJ1ZX0.`
- unverified: `eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJlbWFpbF92ZXJpZmllZCI6ZmFsc2V9.`

## Run without Docker
### Frontend
```bash
cd frontend
npm install
npm run dev
```

### Backend
```bash
cd backend
uv sync
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## Lint & Pre-commit
Backend lint:
```bash
cd backend
uv run ruff check .
```

Frontend lint:
```bash
cd frontend
npm run lint
```

Install pre-commit hook:
```bash
cd backend
uv run pre-commit install
uv run pre-commit run --all-files
```

### Backend Migrations
```bash
cd backend
uv run alembic upgrade head
```

If you use Docker Compose services, prefer running migrations inside backend container:
```bash
docker compose exec backend uv run alembic upgrade head
```

Create a new migration:
```bash
cd backend
uv run alembic revision --autogenerate -m "your message"
```

Create a dedicated test database once:
```bash
docker compose exec postgres psql -U postgres -d postgres -c "CREATE DATABASE elin_test;"
```

Run DB schema tests (requires PostgreSQL available at `TEST_DATABASE_URL`):
```bash
cd backend
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/elin_test uv run pytest -q
```

Safety note: `backend/tests/test_user_schema.py` is destructive by design (`drop/create` target tables).
Never point `TEST_DATABASE_URL` to primary database `elin`.

## Environment Variables
Copy `.env.example` and adjust values as needed.
