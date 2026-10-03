# Dataset Request Desk

Running at http://102.202.208.154:8081/

Internal desk for robot teleoperation datasets. Clients ask for episodes, operators assign them, and the client accepts or rejects the delivery.

- `backend/` — Python 3.12 FastAPI API
- `frontend/` — React, TypeScript, and Vite
- `seed/` — episode export and demo accounts

The browser talks only to the API. In Docker, nginx in the web container proxies `/health` and `/api/` to the API, so the session cookie stays on one origin. The frontend never opens Postgres.

`GET /health` returns `{"status": "ok"}`. That is process liveness only. Each request logs one JSON line: `method`, `path`, `status`, `duration_ms`, and `user_id` (null when there is no session). The line has no query string, headers, cookies, or body.

## Run with Docker

From a clean clone, with Docker running:

```bash
docker compose up --build
```

- UI: http://localhost:8080
- API: http://localhost:8000/health
- Postgres: the `db` container, published on `localhost:5432`

Compose waits for Postgres, runs `alembic upgrade head`, then loads `seed/users.json`. Emails that already exist are skipped. The sample episodes are not loaded. An operator or admin imports them with `POST /api/v1/episodes/import` and the file `seed/episodes.csv`.

Copy `.env.example` to `.env` only to override a default. Do not commit `.env`. If port 5432 or 8080 is already taken, set `POSTGRES_PORT` or `WEB_PORT`. Leave the port in `DATABASE_URL` at 5432: that is the port inside the Compose network, and the hostname stays `db`.

| Name | Default |
|---|---|
| `POSTGRES_USER` / `POSTGRES_PASSWORD` / `POSTGRES_DB` | `desk` / `desk` / `dataset_request_desk` |
| `POSTGRES_PORT` / `API_PORT` / `WEB_PORT` | `5432` / `8000` / `8080` |
| `DATABASE_URL` | `postgresql+psycopg://desk:desk@db:5432/dataset_request_desk` |

`POSTGRES_PASSWORD` is applied when the `pgdata` volume is first created. Changing it later does not rotate the password already stored in that volume.

## Run locally without Docker

API, against a Postgres you already have:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
alembic upgrade head
python -m app.seed
uvicorn app.main:app --reload --no-access-log
```

`alembic` and the API use `DATABASE_URL`. When that variable is unset, the API uses `127.0.0.1:5432`.

UI, in another terminal. It proxies `/health` and `/api` to `127.0.0.1:8000`:

```bash
cd frontend
npm install
npm run dev
```

Leave `VITE_API_BASE_URL` unset. The Vite port is `5173`.

## Tests

One command, from `backend/`. Each test creates and drops its own database. The name must end in `_migrate_test`. The suite refuses `dataset_request_desk`, so a run cannot wipe the app database.

```bash
cd backend && .venv/bin/pytest
```

If Postgres is not on port 5432, point the suite at the maintenance database:

```bash
cd backend && MIGRATION_ADMIN_URL=postgresql+psycopg://desk:desk@127.0.0.1:5433/postgres .venv/bin/pytest
```

The tests cover role checks and client isolation, legal and illegal status changes with history, assignment quality, conflicts, the unique episode constraint, the delivery threshold, CSV import idempotency and bad rows, login and inactive users, analytics date bounds and aggregates, and `/health`.

GitHub Actions (`.github/workflows/test.yml`) runs that suite on push and pull request. The job starts Postgres 16 and sets `MIGRATION_ADMIN_URL` to that service. A second job runs `npm ci` and `npm run build` in `frontend/`.

Two overlapping assignment requests are not launched together. The unique constraint is what stops the second insert. The frontend has no test runner. `npm run build` is the UI check.

Style checks:

```bash
cd backend && .venv/bin/ruff check . && .venv/bin/ruff format --check . && .venv/bin/mypy app
cd frontend && npm run build
```

## Seed accounts

| Email | Password | Role |
|---|---|---|
| admin@example.com | admin123 | admin |
| ops1@example.com | ops123 | operator |
| ops2@example.com | ops123 | operator |
| client-a@example.com | client123 | client |
| client-b@example.com | client123 | client |

These are local fixtures. Passwords are stored as Argon2 hashes. Login sets `desk_session` (HttpOnly) and `desk_csrf`. Later `POST`, `PUT`, `PATCH`, and `DELETE` requests send that CSRF value as `X-CSRF-Token`.

## Analytics

`GET /api/v1/analytics?start_date=YYYY-MM-DD&end_date=YYYY-MM-DD` is staff-only. Both dates are required, UTC, and inclusive. The span can be at most 366 days, so one call cannot walk the whole history.

The figures are computed in Postgres: episodes per day and robot, request counts by current status for requests submitted in the window, the median seconds from submission to the first delivery (`percentile_cont`), and the top five task names among `good` episodes. An empty window returns empty lists, zero counts, and a null median.

At 5 million episodes the shape of those queries stays the same. The day/robot aggregate can use `ix_episodes_recorded_at_robot_id`. The top-task query also filters `quality`, and that is the plan I would `EXPLAIN` before adding an index. The median is one pass over the requests submitted in the window, not over the episode table. What would not survive that volume is the importer: it writes one row at a time. I would batch that write. The API would still return aggregates.

## Deployment

The stretch item I picked is deployment.

A public copy is running at http://102.202.208.154:8081/. It is the same Compose stack: Postgres in the `db` container, schema and seed users applied by the `migrate` service, API and nginx UI beside it. Episode rows were imported after startup through `POST /api/v1/episodes/import`. Database files live in the `pgdata` volume. `docker compose down` keeps that volume. `docker compose down -v` deletes it.

On that machine, ports 5432 and 8080 were already in use, so `.env` sets `POSTGRES_PORT=5433` and `WEB_PORT=8081`. `.env` is not in git. It is the place for `POSTGRES_PASSWORD` and the matching `DATABASE_URL`. There is no domain on this host, so there is no TLS certificate yet. The session cookie is therefore not marked `Secure`.
