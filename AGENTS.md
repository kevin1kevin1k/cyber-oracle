# Repository Guidelines

## Project Structure & Module Organization
This repository is a monorepo with separate frontend and backend services:
- `frontend/`: Next.js (App Router + TypeScript) UI.
- `backend/`: FastAPI service with `uv` dependency management.
- `docker-compose.yml`: local orchestration for both services.
- `docs/PRD.md`: product scope and pipeline requirements.

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

## Database Migration Safety (Required)
- Root cause to avoid: backend code/model is updated but DB schema is still on older Alembic revision (for example new column referenced by runtime code but DB does not have it yet).
- You must run migrations whenever a change touches DB runtime contract, including:
  - Alembic revision files under `backend/alembic/versions/`
  - SQLAlchemy models under `backend/app/models/`
  - Runtime code that reads/writes new/renamed/removed DB columns/tables
- Mandatory verification commands after such changes:
  - Host mode: `cd backend && uv run alembic upgrade head && uv run alembic current && cd ..`
  - Docker Compose mode: `docker compose exec backend uv run alembic upgrade head && docker compose exec postgres psql -U postgres -d elin -c "select * from alembic_version;"`
- If Web UI/API returns DB errors like `UndefinedColumn` or `UndefinedTable`, first action is to run the migration commands above, then retry.
- Docker behavior: backend container startup must run `uv run alembic upgrade head` before starting uvicorn to reduce schema drift risk.

## Coding Style & Naming Conventions
- Indentation: 2 spaces for YAML/JSON/Markdown, 4 spaces for Python.
- TypeScript/React: components in `PascalCase`, variables/functions in `camelCase`.
- Python: modules/functions in `snake_case`, Pydantic models in `PascalCase`.
- Keep endpoint schemas explicit in `backend/app/schemas.py`; avoid untyped payload handling.

## Testing Guidelines
- Backend tests should use `pytest` under `backend/tests/` (create as needed).
- Frontend tests should live under `frontend/` (for example `app/**/*.test.tsx`) when added.
- Any change touching `frontend/` must run the full frontend test scope before reporting done (at minimum `cd frontend && npm run lint && npm run test:e2e && npm run build && cd ..`).
- Any change touching `backend/` must run the full backend test scope before reporting done (at minimum `cd backend && TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/elin_test uv run pytest -q && cd ..`, plus migration verification when DB runtime contract changes).
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

Pre-commit hook stability rule:
- Do not use `cd backend && uv sync && uv run pre-commit install && cd ..` as a commit-time recovery step.
- Install pre-commit at system/tool level once (`uv tool install pre-commit && pre-commit install`) so commits do not depend on recreating `backend/.venv`.

Pull requests should include:
- clear summary and impacted area (`frontend`, `backend`, `infra`)
- linked issue or requirement context (`docs/PRD.md` section)
- test evidence (commands + key output)
- UI screenshots for frontend changes
- changed files list in reviewer scan order (top-down): show high-level docs/config first, then backend, then frontend, then tests/helpers
- one-line summary per changed file so reviewers can predict each diff before opening it (avoid surprise files in later sections)
- after the changed files summary, include manual test steps for any behavior not fully covered by automation (or best validated by humans), with expected results for each step
- for important backend changes (DB/schema/API/runtime behavior), update `backend/README.md` in the same change set
- after each implementation batch, review `docs/TODO.md` and update checklist/progress notes when status has changed
- any update to `docs/PRD.md` must include a same-change-set version bump in the PRD document metadata
- in `docs/TODO.md`, represent partial progress as checkbox subtasks (subitems) instead of plain text progress lines like `進度：...`
- in `docs/TODO.md`, if all subtasks under a parent task are checked, the parent task must also be checked in the same update
- when introducing new libraries/packages, include a short explainer in the reply covering each package's purpose and practical alternatives
- when reporting verification commands, always provide fully executable commands with concrete values (never placeholders like `...`)
- when commands require entering subdirectories (for example `backend`/`frontend`), include a final command to return to project root (for example `cd ..`)
- prefer single-line commands chained with `&&` for reproducibility; only use line continuations (`\`) when readability clearly benefits
- if a command becomes too long (for example with long env vars), use `\` line continuations to keep it copy-paste safe as one command

## Response Format & Language
- For every implementation report response, always use Traditional Chinese.
- For `/review` slash command responses, always use Traditional Chinese (technical terms may remain in English).
- For every implementation report response, always include these sections in order:
  1. `實作結果摘要` (clear summary + impacted area)
  2. `修改檔案` (reviewer scan order: docs/config -> backend -> frontend -> tests/helpers; include one-line summary per file; always use ordered numbering `1. 2. 3.` instead of bullet points)
  3. `測試方式與結果` (fully executable commands with concrete values, plus key outputs)
  4. `人工驗證步驟` (only for behavior not fully covered by automation; include expected result per step)

## Security & Configuration Tips
- Do not commit secrets. Keep runtime values in `.env` and local overrides (ignored by `.gitignore`).
- Use `NEXT_PUBLIC_API_BASE_URL=http://localhost:8000` for browser-based local development.
- Keep CORS origins explicit via `CORS_ORIGINS` in backend environment variables.
