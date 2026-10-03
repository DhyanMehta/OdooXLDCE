# CampusOS

Student Organization Management Platform — mentor-demo scope:

1. Members & memberships  
2. Events & ticketing  
3. Announcements & public club site  
4. Administration & permissions  

## Stack

- `frontend/` React + TypeScript + Vite (`5173`)
- `backend/` FastAPI + SQLAlchemy 2 + session cookies (`8000`)
- `database/` Alembic + PostgreSQL

## Auth model

- Password hashing: Argon2 via `pwdlib`
- HttpOnly session cookie + readable CSRF cookie
- Mutating requests require `X-CSRF-Token`
- Role→permission map lives only in `backend/app/core/permissions.py`
- Frontend navigation is filtered from `/auth/me` permissions

## Quick start (PowerShell)

```powershell
# 1) DB env (local Postgres / pgAdmin)
# Ensure database/.env and backend/.env share the same DATABASE_URL

# 2) Migrate + seed
cd backend
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
cd ..
alembic -c database/alembic.ini upgrade head
cd backend
python -m app.seed

# 3) API
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 4) Worker (renewal reminders + simulated email)
python -m app.worker

# 5) Frontend (second terminal)
cd frontend
npm install
npm run dev
```

## Demo accounts

Password for all: `Password123!`

| Email | Role |
| --- | --- |
| `admin@techclub.edu` | Club administrator (Tech Club) |
| `membership@techclub.edu` | Membership manager |
| `events@techclub.edu` | Event organizer |
| `comms@techclub.edu` | Communications officer |
| `member@techclub.edu` | Ordinary member (active membership + ticket) |
| `expired@techclub.edu` | Expired membership |
| `buyer@example.com` | Ordinary buyer |
| `admin@artsclub.edu` | Admin of second club (authz isolation) |

Public club page: `/clubs/tech-club`

## Walkthrough

1. Log in as `member@techclub.edu` → Member home shows validity.  
2. Open Spring Hack Night → book **member** ticket → demo pay → My tickets QR.  
3. Log in as `events@techclub.edu` → Check-in with QR token → second attempt rejected.  
4. Log in as `comms@techclub.edu` → publish announcement → run worker → delivery `sent_simulated`.  
5. Log in as `admin@techclub.edu` → Roles handover / Audit history.

## Where rules live

| Concern | Location |
| --- | --- |
| Permissions | `backend/app/core/permissions.py`, `services/rbac.py` |
| Membership dates / eligibility | `services/membership_service.py`, `membership_eligibility.py` |
| Purchases / capacity locks | `services/purchase_service.py` |
| Check-in | `services/event_service.py` |
| Announcements / mailing / reminders | `services/announcement_service.py`, `worker.py` |

## Tests

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
pytest -v
```

Uses PostgreSQL database `campusos_test`.
