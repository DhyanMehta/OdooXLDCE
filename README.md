# CampusOS

Student organization management. Four modules only:

1. Members & memberships  
2. Events & ticketing  
3. Announcements & public club site  
4. Administration & permissions  

## Layout

| Folder | Role |
| --- | --- |
| `frontend/` | React + TypeScript + Vite (`http://127.0.0.1:5173`) |
| `backend/` | FastAPI + SQLAlchemy 2 (`http://127.0.0.1:8000`) |
| `database/` | Alembic migrations + DB env / docs |

Dependencies:

- Backend → `backend/pyproject.toml` (no `requirements.txt`)
- Frontend → `frontend/package.json`

## Auth (sessions)

- Passwords: Argon2 (`pwdlib`)
- Server-side rows in `sessions` (token stored as SHA-256 hash)
- Cookie `campusos_session` — HttpOnly, SameSite=Lax
- CSRF cookie `campusos_csrf` + header `X-CSRF-Token` on POST/PATCH/etc.
- Roles → permissions only in `backend/app/core/permissions.py`
- UI sidebar is filtered from `/api/v1/auth/me`

## Setup (PowerShell)

### 1) Database

Use local PostgreSQL (pgAdmin). Create DB `campusos` if needed, then:

```powershell
Copy-Item database\.env.example database\.env
Copy-Item backend\.env.example backend\.env
```

Put the **same** `DATABASE_URL` in both `.env` files, for example:

```text
postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/campusos
```

### 2) Backend

```powershell
cd backend
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd ..
alembic -c database/alembic.ini upgrade head
cd backend
python -m app.seed
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

### 3) Notification worker (optional second terminal)

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.worker
```

### 4) Frontend

```powershell
cd frontend
Copy-Item .env.example .env
npm install
npm run dev
```

Open `http://127.0.0.1:5173` (match Vite host with CORS origins in `backend/.env`).

## Demo accounts

Password for all: `Password123!`

| Email | Use for |
| --- | --- |
| `member@techclub.edu` | Membership, buy tickets, QR |
| `admin@techclub.edu` | Full Admin sidebar |
| `events@techclub.edu` | Events + check-in |
| `comms@techclub.edu` | Announcements + mailing list |
| `membership@techclub.edu` | Plans / members |
| `expired@techclub.edu` | Expired membership |
| `buyer@example.com` | Ordinary buyer |
| `admin@artsclub.edu` | Second club (auth isolation) |

Public club: `/clubs/tech-club`

## Mentor walkthrough

1. Login as **Member** → Home → Events → book member ticket → demo pay → My tickets → copy check-in code  
2. Login as **Events** → Admin → Check-in → first OK, second rejected  
3. Login as **Comms** → publish announcement → run worker → delivery `sent_simulated`  
4. Login as **Admin** → Roles / Audit / Manage events (set prices, draft vs publish)

## Where business rules live

| Area | Code |
| --- | --- |
| Permissions | `backend/app/core/permissions.py`, `services/rbac.py` |
| Membership dates | `services/membership_service.py`, `membership_eligibility.py` |
| Payments / capacity | `services/purchase_service.py` |
| Check-in | `services/event_service.py` |
| Announcements / mail | `services/announcement_service.py`, `worker.py` |

## Tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -v
```

Uses PostgreSQL database `campusos_test`.
