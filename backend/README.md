# CampusOS Backend

FastAPI modular monolith (memberships, events, announcements, admin, merch/projects, club finance).

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
# From repo root (venv active): alembic -c database/alembic.ini upgrade head
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
python -m app.seed   # refuses APP_ENV=production; idempotent; prints LIVE check-in QR
```

### Worker (production entrypoint)

```powershell
campusos-worker --loop
```

`campusos-worker` only standardizes process startup (same as `python -m app.worker`). It does **not** supervise, restart, or pool workers — run one or more processes under your service manager. Each process owns one long-lived async engine (`WORKER_DB_POOL_SIZE` / `WORKER_DB_MAX_OVERFLOW`).

| Flag / env | Purpose |
| --- | --- |
| `--loop` | Continuous polling until Ctrl+C / SIGTERM |
| `--once` | Single pass then exit |
| `--interval` / `WORKER_INTERVAL_SECONDS` | Delivery poll interval |
| `--reminder-interval` / `WORKER_REMINDER_INTERVAL_SECONDS` | Renewal reminder scan interval |
| `WORKER_CLAIM_SECONDS` | Reclaim abandoned `processing` claims |

Dev adapter output: `app/var/email_outbox/` (simulated; no external SMTP in this build).

Expense receipts: local files under `RECEIPT_STORAGE_DIR` (default `app/var/receipts/`). Metadata lives in Postgres; back up the directory with the host. No cloud object store is configured.

Club finance is **bookkeeping only**: demo payments post to `demo_clearing`; refunds are manual recordings (no payment-provider payout).

## Tests

```powershell
pytest -v
```

Requires explicit `TEST_DATABASE_URL` → allowlisted DB (`campusos_test`). Schema comes from Alembic.
