# Dataset Request Desk

Internal platform for requesting and fulfilling robot teleoperation datasets.

This repository is a monorepo:

- `backend/` — Python 3.12 FastAPI API
- `frontend/` — React, TypeScript, and Vite
- `seed/` — provided episode export and user accounts

The browser talks only to the API over HTTP. In Docker, nginx on the web service proxies `/health` and `/api/` to the API so the UI and API share one origin. That keeps a later HttpOnly session cookie first-party. The frontend never connects to PostgreSQL.

## What works now

`GET /health` returns `{"status": "ok"}`. That response is process liveness only: it does not check Postgres. Each request writes one JSON log line with `method`, `path`, `status`, `duration_ms`, and `user_id` (`null` until authentication exists). The log does not include query strings, headers, cookies, or bodies. The API reads `DATABASE_URL` at startup and does not open a connection.

The relational schema is applied by Alembic, then demo users are seeded. Request, episode, import, and analytics endpoints are not built yet. A healthy stack means Postgres accepts connections, migrations have run, and `GET /health` answers. `/health` still does not check the database.

## Ports and environment

Names live in `.env.example`. Compose uses those values when `.env` exists, and the same defaults otherwise.

| Name | Default | Where it applies |
|---|---|---|
| `POSTGRES_PORT` | `5432` | Host port for Postgres |
| `API_PORT` | `8000` | Host port for the API |
| `WEB_PORT` | `8080` | Host port for the UI in Compose |
| `POSTGRES_USER` | `desk` | Postgres role |
| `POSTGRES_PASSWORD` | `desk` | Local placeholder only |
| `POSTGRES_DB` | `dataset_request_desk` | Database name |
| `DATABASE_URL` | `postgresql+psycopg://desk:desk@db:5432/dataset_request_desk` | API database URL. Hostname `db` is the Compose service. If unset, local uvicorn falls back to `127.0.0.1`. |
| `COOKIE_SECURE` | `false` | Set `true` behind HTTPS so session cookies are `Secure`. |
| `SESSION_TTL_SECONDS` | `43200` | Session lifetime. |

Local `npm run dev` serves the UI at http://127.0.0.1:5173 and proxies `/health` and `/api` to http://127.0.0.1:8000. That UI port is fixed in `frontend/vite.config.ts`.

## Run with Docker

From a clean clone, with Docker running:

```bash
docker compose up --build
```

- UI: http://localhost:8080
- API: http://localhost:8000/health
- Postgres: `localhost:5432`

Copy `.env.example` to `.env` only if you need to override those local placeholders. Do not commit `.env`.

## Run locally without Docker

API:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --no-access-log
```

`alembic upgrade head` uses `DATABASE_URL`, or `127.0.0.1` when that variable is unset. Migration tests create and drop only `dataset_request_desk_migrate_test`. If Postgres is not on port 5432, set `MIGRATION_ADMIN_URL` to the maintenance database, for example `postgresql+psycopg://desk:desk@127.0.0.1:5432/postgres`.

UI (separate terminal; proxies `/health` and `/api` to `127.0.0.1:8000`):

```bash
cd frontend
npm install
npm run dev
```

## Tests and checks

```bash
cd backend
source .venv/bin/activate
ruff check .
ruff format --check .
mypy app
pytest
```

```bash
cd frontend
npm run build
```

## Auth

`POST /api/v1/auth/login` sets two cookies: `desk_session` (HttpOnly) and `desk_csrf` (readable by the page). Send the CSRF value back as `X-CSRF-Token` on later `POST`, `PUT`, `PATCH`, and `DELETE` requests. Login itself does not require that header. `GET /api/v1/auth/me` returns the session user. `POST /api/v1/auth/logout` clears the session.

Local seed, from `backend/` after migrations:

```bash
python -m app.seed
```

Compose does this after `alembic upgrade head`. The command reads `seed/users.json` and skips emails that already exist. Only the password hash is stored.

| Email | Password | Role |
|---|---|---|
| admin@example.com | admin123 | admin |
| ops1@example.com | ops123 | operator |
| ops2@example.com | ops123 | operator |
| client-a@example.com | client123 | client |
| client-b@example.com | client123 | client |

These are the task's local fixtures, not production secrets.
