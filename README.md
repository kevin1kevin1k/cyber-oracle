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
- `POST /api/v1/ask`

`POST /api/v1/ask` requires `Authorization: Bearer <token>`.
For current dev stage, token payload must include `email_verified` boolean.

Example:
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

## Environment Variables
Copy `.env.example` and adjust values as needed.
