# Backend

FastAPI backend for ELIN 神域引擎。
Root README only provides monorepo navigation; backend operational details are maintained here as the single source of truth.

## Environment Setup
```bash
cp backend/.env.example backend/.env
```

Then update `backend/.env` with your local values (for example `OPENAI_API_KEY`, `DATABASE_URL`, `JWT_SECRET`).

## Local Development
```bash
uv sync
uv run uvicorn app.main:app --reload --reload-dir app --reload-exclude '.venv/*' --reload-exclude '.git/*' --reload-exclude '__pycache__/*' --host 0.0.0.0 --port 8000
```

Docker Compose backend startup runs migrations automatically before uvicorn:
```bash
uv run alembic upgrade head && uv run uvicorn app.main:app --reload --reload-dir app --reload-exclude '.venv/*' --reload-exclude '.git/*' --reload-exclude '__pycache__/*' --host 0.0.0.0 --port 8000
```

Local Docker Compose isolates `/app/.venv` into a container-only volume so the container does not try to reuse the host `backend/.venv`. This avoids `uv sync` warnings about a virtual environment linked to a non-existent interpreter inside the container.

Production container startup should not use `--reload`:
```bash
uv run alembic upgrade head && uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Auth APIs (Messenger-primary MVP)
- Email/password auth flows are disabled:
  - `POST /api/v1/auth/register`
  - `POST /api/v1/auth/login`
  - `POST /api/v1/auth/verify-email`
  - `POST /api/v1/auth/resend-verification`
  - `POST /api/v1/auth/forgot-password`
  - `POST /api/v1/auth/reset-password`
  - all return `410 AUTH_FLOW_DISABLED`
- `POST /api/v1/auth/logout`
  - revokes current session by token `jti` and returns `204`
- `POST /api/v1/messenger/link`
  - validates a signed Messenger linking token
  - creates a new internal user for an unlinked PSID/page pair, or restores session for an already linked identity
  - returns HS256 bearer token with `sub` + `jti` claims
  - creates a `sessions` record for token revocation/expiration checks

## User Profile APIs
- `GET /api/v1/me/profile`
  - requires authenticated session
  - returns `full_name`, `mother_name`, and `is_complete`
- `PUT /api/v1/me/profile`
  - requires authenticated session
  - updates the fixed ask-profile fields used for question augmentation
  - both `full_name` and `mother_name` are required and trimmed server-side
- `DELETE /api/v1/me`
  - requires authenticated session
  - hard deletes current user account data (`wallet balance`, `question history`, `sessions`, profile fields)
  - resets linked Messenger identities back to `unlinked`, so the same Messenger account can re-run onboarding as a fresh user

## Ask API (credit flow)
- `POST /api/v1/ask`
  - requires authenticated session
  - also requires completed user profile (`full_name` + `mother_name`)
  - supports `Idempotency-Key` request header
  - runtime uses OpenAI file search pipeline (`openai_integration/openai_file_search_lib.py`)
  - default pipeline is one-stage (`OPENAI_ASK_PIPELINE=one_stage`), switchable to two-stage
  - `source` is now runtime-generated (`rag` / `openai`), no longer fixed `mock`
  - answer body is now normalized into a fixed five-part format:
    - `🔮 結論`
    - `🧭 分層解析`
    - `🪶 神諭籤詩`
    - `🪞 籤詩解讀`
    - `⚓ 定錨語`
  - response now includes `followup_options` (0..3 model-generated followup options)
  - backend augments the model input with per-user fixed fields (`full_name`, `mother_name`), but persisted `questions.question_text` remains the raw user-entered question
  - credit flow:
    - success: `reserve -> persist question/answer -> capture`
    - processing failure: `reserve -> refund`
  - integration errors:
    - `500 OPENAI_NOT_CONFIGURED`: missing/invalid OpenAI settings or manifest
    - `502 OPENAI_ASK_FAILED`: upstream OpenAI request failed or returned empty output
  - returns `402` with `INSUFFICIENT_CREDIT` when balance is not enough
  - returns `409 PROFILE_INCOMPLETE` when fixed ask-profile fields are missing
  - duplicate retries with same `Idempotency-Key` replay previous successful response and do not double-charge

## Followup APIs
- `POST /api/v1/followups/{id}/ask`
  - requires authenticated session
  - asks the selected followup in the same topic and charges 1 credit
  - followup item is one-time use (`pending -> used`)
  - returns `FOLLOWUP_NOT_FOUND` / `FOLLOWUP_OWNER_MISMATCH` / `FOLLOWUP_ALREADY_USED` when invalid

## Credits APIs
- `GET /api/v1/credits/balance`
  - requires bearer token
  - returns current wallet balance, `updated_at`, and `payments_enabled`
  - if wallet does not exist yet, returns `balance=0`, `updated_at=null`, and current payments flag
- `GET /api/v1/credits/transactions`
  - requires bearer token
  - query params: `limit` (1-100, default 20), `offset` (default 0)
  - returns user-scoped transaction list (newest first) and total count

## History APIs
- `GET /api/v1/history/questions`
  - requires bearer token
  - query params: `limit` (1-50, default 20), `offset` (default 0)
  - returns user-scoped ask history root questions only (newest first)
  - followup child questions are excluded from list
  - each item includes:
    - `question_id`, `question_text`, `answer_preview`, `source`, `charged_credits`, `created_at`
  - `charged_credits` is derived from `capture` credit transactions for that question
- `GET /api/v1/history/questions/{question_id}`
  - requires bearer token
  - returns full root-conversation detail for the authenticated user
  - when `{question_id}` is a followup child, response is normalized to its root conversation
  - `404 QUESTION_NOT_FOUND` when resource is missing or not owned by current user
  - response includes:
    - `root` question node (full `answer_text`, `layer_percentages`, `charged_credits`, `request_id`)
    - recursive `children` nodes built from followup ask relationships
    - `transactions` list (`capture`/`refund`) for all questions in this followup tree

## Orders APIs
- `POST /api/v1/orders`
  - requires bearer token
  - creates pending order for package size `1|3|5` and mapped amount `168|358|518`
  - request requires `idempotency_key`; duplicate key for same user replays existing order
  - when `PAYMENTS_ENABLED=false`, returns `403 PAYMENTS_DISABLED`
- `POST /api/v1/orders/{id}/simulate-paid`
  - requires bearer token
  - marks pending order as paid, grants credits to wallet, and writes `purchase` credit transaction
  - idempotent for already-paid orders (no duplicate credit grant)
  - disabled when `APP_ENV=prod` (returns `FORBIDDEN_IN_PRODUCTION`)

## Database
- Primary DB: PostgreSQL
- Default local URL: `postgresql+psycopg://postgres:postgres@localhost:5432/elin`
- Docker Compose URL (inside container): `postgresql+psycopg://postgres:postgres@postgres:5432/elin`

Environment variables:
- `APP_ENV`: runtime env (`dev` / `test` / `prod`, default `dev`)
- `CORS_ORIGINS`: comma-separated browser origins allowed to call backend APIs (must include public frontend/WebView origins such as Messenger frontend tunnel URLs)
- `DATABASE_URL`: app runtime database
  - accepts both `postgresql+psycopg://...` and raw Render-style `postgresql://...`; backend startup normalizes the latter to `postgresql+psycopg://...`
- `TEST_DATABASE_URL`: test-only database (use `elin_test`)
- `JWT_SECRET`: HS256 signing secret for access token
- `JWT_ALGORITHM`: JWT algorithm (default `HS256`)
- `JWT_EXP_MINUTES`: access token expiration in minutes (default `60`)
- `PAYMENTS_ENABLED`: enables/disables order creation and launch purchase UI capability
- `LAUNCH_CREDIT_GRANT_AMOUNT`: one-time credit amount granted after successful Messenger link
- `MESSENGER_ENABLED`: enable Messenger webhook routes (`false` by default)
- `META_VERIFY_TOKEN`: webhook verify token (required when `MESSENGER_ENABLED=true`)
- `META_PAGE_ACCESS_TOKEN`: required when `MESSENGER_OUTBOUND_MODE=meta_graph`
- `META_APP_SECRET`: used for `X-Hub-Signature-256` validation
- `MESSENGER_VERIFY_SIGNATURE`: enable webhook signature validation (`false` by default)
- `MESSENGER_OUTBOUND_MODE`: outbound client mode (`noop` or `meta_graph`)
- `MESSENGER_WEB_BASE_URL`: frontend/WebView base URL used in Messenger web_url buttons (`http://localhost:3000` by default; set to your public frontend URL in local tunnel / staging / production)
- `MESSENGER_PROFILE_SYNC_ON_STARTUP`: when `true`, backend startup performs best-effort Messenger profile sync (`greeting` + `Get Started` + `persistent_menu`) using current env; failures are logged as warnings and do not block service startup

Docker Compose note:
- local Compose should not hardcode `CORS_ORIGINS=http://localhost:3000` in service env, otherwise public frontend tunnel origins from `backend/.env` will be ignored and browser preflight (`OPTIONS`) requests from Messenger WebView will fail with `400`
- when frontend tunnel URL changes, update both `MESSENGER_WEB_BASE_URL` and `CORS_ORIGINS` in `backend/.env`, then restart backend

Production security baseline:
- when `APP_ENV=prod`, backend startup validates `JWT_SECRET` and fails fast if:
  - value is empty
  - value equals development default (`dev-only-change-me-please-replace-32+`)
  - value length is shorter than 32 characters
- when `APP_ENV=prod`, backend also validates:
  - `MESSENGER_VERIFY_SIGNATURE=true` if Messenger is enabled
  - `META_APP_SECRET` is configured if Messenger signature verification is enabled

Launch-mode guidance:
- for the current public beta launch shape, set `PAYMENTS_ENABLED=false`
- new Messenger-linked users receive one-time launch credits via `LAUNCH_CREDIT_GRANT_AMOUNT`
- if launch credits need to be backfilled manually, use:
```bash
cd /Users/kevin1kevin1k/cyber-oracle/backend && uv run python scripts/grant_launch_credits.py --email target@example.com && cd ..
```

Production deployment baseline:
- Render is the default production target for this repo
- recommended domains:
  - frontend / WebView: `https://app.<your-domain>`
  - backend API: `https://api.<your-domain>`
- minimum production env contract:
  - backend: `APP_ENV=prod`, `DATABASE_URL`, `JWT_SECRET`, `OPENAI_API_KEY`, `VECTOR_STORE_ID`, `CORS_ORIGINS=https://app.<your-domain>`, `PAYMENTS_ENABLED=false`, `MESSENGER_ENABLED=true`, `META_VERIFY_TOKEN`, `META_PAGE_ACCESS_TOKEN`, `META_APP_SECRET`, `MESSENGER_VERIFY_SIGNATURE=true`, `MESSENGER_OUTBOUND_MODE=meta_graph`, `MESSENGER_WEB_BASE_URL=https://app.<your-domain>`
  - frontend: `NEXT_PUBLIC_API_BASE_URL=https://api.<your-domain>`
- repo blueprint:
  - `render.yaml` defines the baseline `frontend + backend + postgres` Render topology
- production launch / smoke test / rollback steps:
  - see `docs/production_launch_runbook.md`

## Messenger Integration (Skeleton)
This repository now includes a non-invasive Messenger channel adapter skeleton under `app/messenger/`.

- verification, webhook binding, persistent menu sync, local/pre-prod/prod validation, and Meta setup steps are documented in `docs/messenger_validation_runbook.md`

Endpoints:
- `GET /api/v1/messenger/webhook`
  - Meta webhook verification endpoint (`hub.mode`, `hub.verify_token`, `hub.challenge`)
  - returns challenge in `text/plain` when verify token matches
- `POST /api/v1/messenger/webhook`
  - parses basic Messenger events (`message`, `quick reply`, `postback`)
  - returns `200 accepted` quickly after verify/parse, then processes ask/followup/send in background task
  - resolves/creates `messenger_identities` mapping
  - for linked identities, text messages now execute the existing ask credit flow (`reserve -> capture/refund`)
  - maps ask followups into a single Messenger quick-replies message, and quick reply clicks now reuse the existing followup ask flow
  - followups are expected to be direct next-step questions, not questionnaire-style prompts that ask the user to choose or provide missing fields first
  - dispatches outgoing payloads through pluggable client abstraction (`noop` or `meta_graph`)
  - `POST /api/v1/messenger/link` is the WebView session bootstrap endpoint; it links a new user or restores an existing linked identity and grants launch credits once

Current channel capabilities:
- `noop`: local/dev ingest-only mode, webhook can be tested without real Messenger reply
- `meta_graph`: minimum viable Graph Send API implementation for:
  - text messages
  - quick replies
  - button templates
- linked/unlinked routing, Messenger WebView session bootstrap, quick reply followups, re-show followups after top-up, and persistent menu (`查看剩餘點數` / `前往設定`)
- `前往設定` persistent menu entry now uses postback bridge flow: Messenger first receives a signed WebView button, then opens the single-page WebView settings center with session bootstrap
- linked users who have not filled `full_name` / `mother_name` are guided to `/settings` before ask/followup execution
- when a linked user sends a text question before completing `full_name` / `mother_name`, backend stores a pending Messenger ask and returns both `/settings` and replay buttons so the original question can be resent after profile completion
- direct ask / followup / replay now send best-effort `mark_seen` + `typing_on` before long-running OpenAI execution, then `typing_off` before the final reply so the user sees processing feedback instead of a long silent gap
- direct ask / followup / replay success replies now send a separate remaining-credit message (`本次已扣 1 點，目前剩餘 X 點。`) before the final answer/quick-replies message, so followup buttons remain attached to the last outgoing message
- when `PAYMENTS_ENABLED=false`, insufficient-credit flows return a read-only wallet / no-purchase experience instead of purchase buttons
- direct ask insufficient-credit recovery now stores a pending Messenger ask and lets the user replay the exact question after top-up with a single postback
- Messenger profile sync now sets `greeting`, `get_started`, and `persistent_menu`, because Meta requires `Get Started` before persistent menu can be enabled and greeting improves first-open onboarding
- `GET_STARTED` now acts as a real onboarding entry: unlinked users or linked users with incomplete profile receive a signed WebView button that opens `/?from=messenger-get-started`
- backend startup can auto-sync Messenger profile when `MESSENGER_PROFILE_SYNC_ON_STARTUP=true`; keep `backend/scripts/sync_messenger_profile.py` as manual fallback after token rotation or emergency menu refresh
- failure handling:
  - ask / replay / followup failures are classified into config / upstream / generic user-facing Messenger replies instead of a single fallback for every case
  - outbound send failures are logged and do not turn webhook ingest into `500`
  - webhook ingest and OpenAI/send execution are now decoupled via FastAPI background task to reduce Meta timeout / local tunnel `context canceled`
  - retry / dead-letter / telemetry are not implemented yet

Schema/Model:
- `messenger_identities` table stores `platform/psid/page_id` and optional `user_id` link.
- Unlinked state is supported (`user_id=NULL`, `status=unlinked`) for pre-linking interactions.

Current status (explicitly non-production-complete):
  - implemented: webhook adapter routes, identity mapping table, linked/unlinked routing, Messenger WebView account linking MVP, inbound ask flow reuse, quick reply followup reuse, minimum viable Meta Graph outbound send, tests
- not implemented yet: production-ready retry/telemetry, full webhook replay protection, policy/compliance hardening
- not implemented yet: Messenger in-flow Stripe checkout and payment callback closed loop

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

Troubleshooting schema drift (`UndefinedColumn` / `UndefinedTable`):
```bash
docker compose exec backend uv run alembic upgrade head && docker compose exec postgres psql -U postgres -d elin -c "select * from alembic_version;"
```

## Tests
Create test DBs once:
```bash
docker compose exec postgres psql -U postgres -d postgres -c "CREATE DATABASE elin_test;" && docker compose exec postgres psql -U postgres -d postgres -c "CREATE DATABASE elin_test_destructive;"
```

Run general backend tests:
```bash
TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/elin_test uv run pytest -q
```

Run destructive schema tests separately:
```bash
DESTRUCTIVE_TEST_DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/elin_test_destructive uv run pytest -q tests/destructive/test_user_schema_destructive.py
```

Safety note:
- `backend/tests/destructive/test_user_schema_destructive.py` is destructive for target tables and must use `DESTRUCTIVE_TEST_DATABASE_URL`, not `TEST_DATABASE_URL`.
- Never point either `TEST_DATABASE_URL` or `DESTRUCTIVE_TEST_DATABASE_URL` to primary DB `elin`.
- Never point destructive tests at shared test DB `elin_test`; use `elin_test_destructive` instead.
- Do not run multiple `pytest` commands in parallel against the same test DB. Shared `drop/create/delete` activity will cause false failures such as `relation does not exist`, cross-table FK violations, or `cannot drop table ... because other objects depend on it`.
- Docker Compose runtime backend should keep using the development DB `elin`; do not reuse test DB URLs for normal app startup or manual web/Messenger testing.

## Lint and Hooks
Run backend lint:
```bash
uv run ruff check .
```

Install and run pre-commit without coupling to `backend/.venv`:
```bash
uv tool install pre-commit && pre-commit install
pre-commit run --all-files
```

## OpenAI File Search (cyber oracle)
This repo includes helper scripts for one-stage/two-stage Responses flow:
1) one-time vector store build + persist `rag_files` mapping in manifest
2) one-time input files upload + persist `input_files` mapping in manifest
3) query-time one-stage or two-stage response with structured output (`conclusion` / `layered_analysis` / `oracle_poem` / `poem_interpretation` / `anchoring_phrase` + `followup_options`)

```mermaid
sequenceDiagram
  participant Builder as 1. openai_vector_store_builder.py
  participant Uploader as 2. openai_input_files_uploader.py
  participant Main as 3. openai_file_search_main.py
  participant Lib as 3.1 openai_file_search_lib.py
  participant Env as .env
  participant Manifest as input_files_manifest.json
  participant VS as OpenAI Vector Store
  participant Files as OpenAI Files
  participant Resp as OpenAI Responses API

  Builder->>VS: upload rag_files + create/update vector store
  Builder->>Env: persist VECTOR_STORE_ID
  Builder->>Manifest: write rag_files mapping

  Uploader->>Files: upload input_files
  Uploader->>Manifest: write input_files mapping (preserve existing rag_files)

  Main->>Lib: run_two_stage_response(question)
  Lib->>Env: read OPENAI_API_KEY + VECTOR_STORE_ID
  Lib->>Manifest: read input_files + rag_files mapping
  Lib->>Resp: 3.2 first responses.create + tools.file_search(top3)
  Resp-->>Lib: top3 matches from vector store
  Lib->>Manifest: 3.3 map top3 rag files -> input_files ids
  Lib->>Resp: 3.4 second responses.create with mapped files
  Resp-->>Main: final response_text
```

Environment variables:
- `OPENAI_API_KEY`: OpenAI API key in `backend/.env`
- `VECTOR_STORE_ID`: vector store id used by file search (auto-written by vector store builder)
- production / Render runtime reads `OPENAI_API_KEY` and `VECTOR_STORE_ID` from process environment first, then falls back to local `backend/.env`
- production / Render runtime treats `openai_integration/input_files_manifest.json` as optional; if the manifest is missing, ask flow still runs against `VECTOR_STORE_ID` and skips reusable `input_files` attachment
- `OPENAI_ASK_PIPELINE`: ask pipeline mode (`one_stage` default, optional `two_stage`)

Build or refresh vector store from local files:
```bash
cd backend && uv run python -m openai_integration.openai_vector_store_builder --rag-files-dir ~/Downloads/cyber_oracle_files/algorithms --vector-store-name cyber-oracle-knowledge --manifest-path openai_integration/input_files_manifest.json && cd ..
```

Dry-run (list eligible files only, no API calls):
```bash
cd backend && uv run python -m openai_integration.openai_vector_store_builder --rag-files-dir ~/Downloads/cyber_oracle_files/algorithms --manifest-path openai_integration/input_files_manifest.json --dry-run && cd ..
```

Upload reusable `input_files` once and write manifest:
```bash
cd backend && uv run python -m openai_integration.openai_input_files_uploader --input-files-dir ~/Downloads/cyber_oracle_files/input_files --manifest-path openai_integration/input_files_manifest.json && cd ..
```

Ask one question with the reusable library via CLI (`--pipeline two_stage|one_stage`, default `two_stage`):
```bash
cd backend && uv run python -m openai_integration.openai_file_search_main --question "請根據文件回答：ELIN 的核心流程是什麼？" --manifest-path openai_integration/input_files_manifest.json --pipeline two_stage && cd ..
```

Use library in backend code:
```python
from pathlib import Path

from openai_integration.openai_file_search_lib import OpenAIFileSearchClient

client = OpenAIFileSearchClient(model="gpt-5.2-2025-12-11")
result = client.run_two_stage_response(
    question="請根據 cyber oracle 文件回答我的問題",
    manifest_path=Path("openai_integration/input_files_manifest.json"),
    system_prompt="你是 ELIN 文件助手。",
    top_k=3,
)
print(result.response_text)
```

Troubleshooting:
- If file search fails with missing `rag_files` mapping, rerun vector store builder:
```bash
cd backend && uv run python -m openai_integration.openai_vector_store_builder --rag-files-dir ~/Downloads/cyber_oracle_files/algorithms --vector-store-name cyber-oracle-knowledge --manifest-path openai_integration/input_files_manifest.json && cd ..
```
- If file search fails with missing `input_files` mapping, rerun uploader:
```bash
cd backend && uv run python -m openai_integration.openai_input_files_uploader --input-files-dir ~/Downloads/cyber_oracle_files/input_files --manifest-path openai_integration/input_files_manifest.json && cd ..
```
- If Render / production has no local `input_files_manifest.json`, this is no longer a blocker. The runtime will fall back to vector-store-only search; only local workflows that depend on reusable `input_files` need the uploader/manifest.
