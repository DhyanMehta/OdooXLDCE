# CampusOS Database

PostgreSQL + Alembic for the four selected modules.

## Current schema

Migration: `migrations/versions/538fc085a8ba_campusos_core_schema.py`

| Area | Tables |
| --- | --- |
| Identity / auth | `users`, `sessions`, `clubs`, `club_members`, `roles`, `club_role_assignments`, `audit_logs` |
| Membership | `membership_plans`, `memberships` |
| Checkout | `orders`, `order_items`, `payments`, `payment_events` |
| Events | `events`, `ticket_types`, `ticket_prices`, `tickets`, `ticket_checkins` |
| Comms | `announcements`, `mailing_list_subscriptions`, `notification_deliveries` |

Design rules:

- `club_members` = affiliation; `memberships` = paid entitlement (separate)
- Roles hang off club affiliation, not off buying a plan
- Order items snapshot unit price; membership quantity must be `1`
- Ticket QR: hash for check-in (+ sealed value for owner re-display)
- Duplicate check-in blocked by unique `ticket_id` on `ticket_checkins`
- No merchandise / inventory / ledger tables in this demo

## Credentials

Keep these aligned:

| File | Fields |
| --- | --- |
| `database/.env` | `POSTGRES_*` (Compose) + `DATABASE_URL` (Alembic) |
| `backend/.env` | `DATABASE_URL` (same user / password / db) |

Example shape (change password to yours):

```text
POSTGRES_USER=postgres
POSTGRES_PASSWORD=YOUR_PASSWORD
POSTGRES_DB=campusos
DATABASE_URL=postgresql+psycopg://postgres:YOUR_PASSWORD@localhost:5432/campusos
```

This team uses **local PostgreSQL 18 + pgAdmin 4** (not Docker) for day-to-day work.

## Local PostgreSQL / pgAdmin

1. Create database `campusos` (owner can be `postgres` or a dedicated role).
2. Copy `.env.example` → `.env` and set matching credentials.
3. In pgAdmin: host `127.0.0.1`, port `5432`, database `campusos`.

Optional Docker (Compose file at repo root) if you prefer containers:

```powershell
Copy-Item database\.env.example database\.env
docker compose up -d
```

## Alembic (from repo root)

Needs backend editable install so `app` models import:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
cd ..
alembic -c database/alembic.ini upgrade head
alembic -c database/alembic.ini current
```

New revision later:

```powershell
alembic -c database/alembic.ini revision --autogenerate -m "describe_change"
alembic -c database/alembic.ini upgrade head
```

## Seed data

Demo clubs, users, plans, events, tickets, announcements:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
python -m app.seed
```

Password for seeded users: `Password123!`  
See root `README.md` for the account table.
