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

## Run without Docker
### Frontend
```bash
cd frontend
npm install
npm run dev
```

## Lint & Pre-commit
Frontend lint:
```bash
cd frontend
npm run lint
```

## Service Docs
- Backend detailed guide: `backend/README.md`
- Frontend implementation currently documented in this root README and source comments.

## Environment Variables
Copy `.env.example` and adjust values as needed.
