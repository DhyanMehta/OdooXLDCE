# CampusOS Backend

FastAPI API service for CampusOS (Phase 1: foundation + health endpoint only).

## Stack

- Python 3.11+
- FastAPI + Uvicorn
- Pydantic Settings
- SQLAlchemy 2 (declarative `Base` ready for later models)
- psycopg 3 driver string in `DATABASE_URL`

## Setup (PowerShell)

From the repository root:

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
```

> Keep the virtual environment at `backend/.venv` only.

## Run

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- Health: http://127.0.0.1:8000/api/v1/health
- OpenAPI: http://127.0.0.1:8000/docs

The health endpoint reports that the API process is running. It does **not** check PostgreSQL.

## Tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest
```

## Environment

See `.env.example`. `DATABASE_URL` must use the same user, password, and database name as `database/.env` (`POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`).

Use the `postgresql+psycopg://` scheme for SQLAlchemy + psycopg 3.
