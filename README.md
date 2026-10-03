# Dataset Request Desk

Internal platform for requesting and fulfilling robot teleoperation datasets.

This repository is a monorepo:

- `backend/` — Python 3.12 FastAPI API
- `frontend/` — React, TypeScript, and Vite
- `seed/` — provided episode export and user accounts

The browser talks only to the API over HTTP. In Docker, nginx on the web service proxies `/health` and `/api/` to the API so the UI and API share one origin. That keeps a later HttpOnly session cookie first-party. The frontend never connects to PostgreSQL.

## What works now

`GET /health` returns `{"status": "ok"}`. Each request writes one JSON log line with `method`, `path`, `status`, `duration_ms`, and `user_id` (`null` until authentication exists).

Domain features (auth, requests, episodes, import, analytics) are not built yet. Compose starts PostgreSQL, but there are no migrations or seed users in the database yet.

## Run with Docker

From a clean clone, with Docker running:

```bash
docker compose up --build
```

- UI: http://localhost:8080
- API: http://localhost:8000/health
- Postgres: `localhost:5432` (user, password, and database `desk` / `desk` / `dataset_request_desk`)

Copy `.env.example` to `.env` only if you need to override those local placeholders. Do not commit `.env`.

## Run locally without Docker

API:

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload --no-access-log
```

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

## Seed accounts

Login is not implemented yet. The accounts to create later are in `seed/users.json`:

| Email | Password | Role |
|---|---|---|
| admin@example.com | admin123 | admin |
| ops1@example.com | ops123 | operator |
| ops2@example.com | ops123 | operator |
| client-a@example.com | client123 | client |
| client-b@example.com | client123 | client |

Passwords in that file are the task's local fixtures. The database must store only password hashes.
