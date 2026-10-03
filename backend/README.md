# CampusOS Backend

FastAPI modular monolith for the four selected modules.

## Auth

- Argon2 password hashes (`pwdlib`)
- Server-side sessions in `sessions` table
- HttpOnly `campusos_session` cookie + `campusos_csrf` cookie
- Mutating requests require header `X-CSRF-Token`
- Permissions: `app/core/permissions.py`

## Setup

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
Copy-Item .env.example .env   # then set DATABASE_URL
```

## Run

```powershell
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
python -m app.seed
python -m app.worker
```

## Tests

```powershell
pytest -v
```

Creates/uses PostgreSQL database `campusos_test`.
