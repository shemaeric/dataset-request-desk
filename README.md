# Dataset Request Desk

Internal platform for requesting and fulfilling robot teleoperation datasets.

This repository is a monorepo:

- `backend/` — Python 3.12 FastAPI API
- `frontend/` — React, TypeScript, and Vite
- `seed/` — provided episode export and user accounts

The browser talks only to the API over HTTP. In Docker, nginx on the web service proxies `/health` and `/api/` to the API so the UI and API share one origin. That keeps a later HttpOnly session cookie first-party. The frontend never connects to PostgreSQL.

## What works now

`GET /health` returns `{"status": "ok"}`. That response is process liveness only: it does not check Postgres. Each request writes one JSON log line with `method`, `path`, `status`, `duration_ms`, and `user_id` (null when there is no session). The log does not include query strings, headers, cookies, or bodies.

The relational schema is applied by Alembic, then demo users are seeded. Login, requests, episode import, and episode search are implemented. Assignment endpoints and analytics are not. A healthy stack means Postgres accepts connections, migrations have run, and `GET /health` answers. `/health` still does not check the database.

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

## Requests

`POST /api/v1/requests` is for clients. The owner is the logged-in user; a `client_id` or `status` in the body is ignored. `GET /api/v1/requests` returns that client's rows, or every row for an operator or admin.

`GET /api/v1/requests/{id}` and `POST /api/v1/requests/{id}/transitions` use one not-found response. A missing id and another client's id both return 404 `Request not found`, so a client cannot tell those cases apart. Operators and admins get that 404 only when the id does not exist. A request they are allowed to see, but with the wrong role for the step, returns 403. Any other status change returns 409 `Invalid status transition`.

Staff (`operator` or `admin`) may move `submitted` to `in_progress`, `rejected` to `in_progress`, and `in_progress` to `delivered`. The owning client may move `delivered` to `accepted` or `rejected`. `delivered` also returns 409 `Not enough episodes assigned` until `assignments` has at least `episodes_requested` rows. Creating a request and each successful transition write the new status and one history row (actor and timestamp) in the same transaction.

`task_name` is 1–200 characters, `episodes_requested` is 1–100000, `deadline` is from today (UTC) through five years ahead, and `notes` are optional up to 2000 characters. Writes need the CSRF header.

## Episodes

`POST /api/v1/episodes/import` takes a CSV file upload. Operators and admins can call it. Clients cannot, and they cannot list episodes either.

The header must be `episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality`. A bad header, a file that is not UTF-8, or a file over 32MB is a 400 and writes nothing. Row problems do not reject the rest of the file. A blank line is ignored.

Import normalizes a row before it stores it: episode ids are uppercased, robots and quality are lowercased, task names are trimmed and lowercased, and timestamps without a zone are UTC. `14/08/2026 09:15` is day-first. Quality must be `good`, `usable`, or `bad`. Duration must be a positive integer. Robots must be one of `arm-01`, `arm-02`, `arm-03`, `mobile-01`, `humanoid-01`, so `arm-99` is reported and not stored.

The same episode id is inserted once, using the unique `source_episode_id` constraint. A later row with the same normalized fields is skipped. A later row with different fields is a conflict: the stored row stays as it was, and the response names the row. Nothing is updated in place. The JSON report has `created`, `skipped`, `conflicts`, `invalid`, and `errors` (row number, episode id, reason). `errors` includes the first 100 invalid or conflicting rows.

`GET /api/v1/episodes` filters by `task_name` and `quality`, using the same task-name normalization. Results are ordered by `source_episode_id`. `limit` defaults to 50 and maxes at 100, with `offset`. The body is `items`, `total`, `limit`, and `offset`.
