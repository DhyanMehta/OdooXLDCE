# CampusOS Database

PostgreSQL infrastructure, Alembic migrations, and future seeds/scripts.

Phase 1 includes migration tooling only — **no business schema migrations yet**.

## Credential correspondence

| Source | Variables |
| --- | --- |
| `database/.env` | `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `DATABASE_URL` |
| `backend/.env` | `DATABASE_URL` (same user/password/db) |

Example:

```
POSTGRES_USER=campusos
POSTGRES_PASSWORD=campusos_dev
POSTGRES_DB=campusos
DATABASE_URL=postgresql+psycopg://campusos:campusos_dev@localhost:5432/campusos
```

## Option A — Docker Compose (recommended for the hackathon)

From the repository root:

```powershell
Copy-Item database\.env.example database\.env
docker compose config
docker compose up -d
docker compose ps
```

PostgreSQL listens on `127.0.0.1:5432` with a named volume `campusos_pgdata`.

## Option B — Existing local PostgreSQL

1. Create a role and database that match `database/.env` / `backend/.env`.
2. Skip Docker Compose.
3. Point both `DATABASE_URL` values at your local instance.

Example with `psql` (adjust for your superuser):

```powershell
psql -U postgres -c "CREATE USER campusos WITH PASSWORD 'campusos_dev';"
psql -U postgres -c "CREATE DATABASE campusos OWNER campusos;"
```

## pgAdmin 4

Use your existing pgAdmin 4 installation (not managed by this repo):

1. Register a server → Host `127.0.0.1`, Port `5432`.
2. Username / password / database from `database/.env`.
3. Maintenance DB can be `postgres` or `campusos`.

## Alembic (from repository root)

Requires the backend editable install so `app.db.base.Base` is importable:

```powershell
cd backend
.\.venv\Scripts\Activate.ps1
cd ..
Copy-Item database\.env.example database\.env
alembic -c database/alembic.ini history
alembic -c database/alembic.ini current
```

Future workflow (do not run for business tables in Phase 1):

```powershell
alembic -c database/alembic.ini revision --autogenerate -m "describe_change"
alembic -c database/alembic.ini upgrade head
```

## Seeds / scripts

`seeds/` and `scripts/` are reserved for later phases. No sample business data is included in Phase 1.
