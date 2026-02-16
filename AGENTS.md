# Repository Guidelines

## Project Structure & Module Organization
This repository is a monorepo with separate frontend and backend services:
- `frontend/`: Next.js (App Router + TypeScript) UI.
- `backend/`: FastAPI service with `uv` dependency management.
- `docker-compose.yml`: local orchestration for both services.
- `PRD.md`: product scope and pipeline requirements.

Frontend app code lives in `frontend/app/`. Backend API code lives in `backend/app/` (`main.py`, `schemas.py`, `config.py`). Keep API contracts and UI integration changes aligned.

## Build, Test, and Development Commands
Primary workflow (recommended):
- `docker compose up --build`: start frontend (`:3000`) and backend (`:8000`).
- `docker compose down`: stop all services.

Frontend local run:
- `cd frontend && npm install`
- `npm run dev`

Backend local run:
- `cd backend && uv sync`
- `uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`

## Coding Style & Naming Conventions
- Indentation: 2 spaces for YAML/JSON/Markdown, 4 spaces for Python.
- TypeScript/React: components in `PascalCase`, variables/functions in `camelCase`.
- Python: modules/functions in `snake_case`, Pydantic models in `PascalCase`.
- Keep endpoint schemas explicit in `backend/app/schemas.py`; avoid untyped payload handling.

## Testing Guidelines
- Backend tests should use `pytest` under `backend/tests/` (create as needed).
- Frontend tests should live under `frontend/` (for example `app/**/*.test.tsx`) when added.
- Minimum API coverage for new endpoints:
  - success path
  - validation failure (4xx)
  - error handling path where applicable
- Always verify `GET /api/v1/health` and `POST /api/v1/ask` after integration changes.

## Commit & Pull Request Guidelines
Use Conventional Commits:
- `feat: add token validation`
- `fix: handle empty config path`
- `docs: add onboarding notes`

Pull requests should include:
- clear summary and impacted area (`frontend`, `backend`, `infra`)
- linked issue or requirement context (`PRD.md` section)
- test evidence (commands + key output)
- UI screenshots for frontend changes

## Security & Configuration Tips
- Do not commit secrets. Keep runtime values in `.env` and local overrides (ignored by `.gitignore`).
- Use `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` for browser-based local development.
- Keep CORS origins explicit via `CORS_ORIGINS` in backend environment variables.
