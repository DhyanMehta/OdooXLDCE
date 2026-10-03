# CampusOS

Student Organization Management Platform — 36-hour hackathon foundation (Phase 1).

Phase 1 delivers a runnable skeleton only: React frontend, FastAPI health API, PostgreSQL via Compose, and Alembic wiring. No business modules, auth, or sample domain data yet.

## Repository layout

```
frontend/     React + TypeScript + Vite (port 5173)
backend/      FastAPI + SQLAlchemy 2 Base (port 8000)
database/     Alembic + Compose env + seeds/scripts placeholders
compose.yaml  PostgreSQL 16 only
```

## Assumptions (Phase 1)

- Python **3.11+** (validated with 3.13 via `py -3.13` on Windows).
- Frontend package manager is **npm** with `package-lock.json`.
- Backend uses a **synchronous** SQLAlchemy stack later; health is process-liveness only.
- `DATABASE_URL` uses the **psycopg 3** scheme: `postgresql+psycopg://...`.
- pgAdmin 4 is an existing local install and is not containerized here.
- Default local credentials (examples only): user `campusos`, password `campusos_dev`, database `campusos`.

## Credential correspondence

| File | Role |
| --- | --- |
| `database/.env` | Compose `POSTGRES_*` + Alembic `DATABASE_URL` |
| `backend/.env` | API `DATABASE_URL` (same user/password/db) |
| `frontend/.env` | `VITE_API_BASE_URL` → API origin |

Example:

```
POSTGRES_USER=campusos
POSTGRES_PASSWORD=campusos_dev
POSTGRES_DB=campusos
DATABASE_URL=postgresql+psycopg://campusos:campusos_dev@localhost:5432/campusos
VITE_API_BASE_URL=http://127.0.0.1:8000
```

## Quick start (PowerShell)

### 1) PostgreSQL (Docker)

```powershell
Copy-Item database\.env.example database\.env
docker compose config
docker compose up -d
docker compose ps
```

### 2) PostgreSQL (existing local install)

Skip Compose. Create a matching role/database, then use the same `DATABASE_URL` in `database/.env` and `backend/.env`. Connect with pgAdmin 4 to host `127.0.0.1`, port `5432`.

### 3) Backend

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

Health: http://127.0.0.1:8000/api/v1/health

### 4) Frontend

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

App: http://127.0.0.1:5173

### 5) Tests & checks

```powershell
# Frontend
cd frontend
npm run typecheck
npm run lint
npm run build

# Backend
cd backend
.\.venv\Scripts\Activate.ps1
pytest

# Alembic import/config validation (no business migrations in Phase 1)
cd <repo-root>
.\backend\.venv\Scripts\Activate.ps1
alembic -c database/alembic.ini history
alembic -c database/alembic.ini current
```

### Future migrations

After models exist:

```powershell
.\backend\.venv\Scripts\Activate.ps1
alembic -c database/alembic.ini revision --autogenerate -m "describe_change"
alembic -c database/alembic.ini upgrade head
```

## pgAdmin 4

1. Open your existing pgAdmin 4.
2. Register server → Host `127.0.0.1`, Port `5432`.
3. Use credentials from `database/.env`.

## Phase boundary

Stop here for Phase 1. Do not add authentication, business tables, fabricated domain endpoints, or seed business data until later phases.
