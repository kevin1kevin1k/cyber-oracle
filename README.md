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

Services:
- Frontend: http://localhost:3000
- Backend health: http://localhost:8000/api/v1/health

## API Endpoints
- `GET /api/v1/health`
- `POST /api/v1/ask`

Example:
```bash
curl -X POST http://localhost:8000/api/v1/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"今天該聚焦什麼？","lang":"zh","mode":"analysis"}'
```

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
