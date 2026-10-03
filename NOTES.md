# Notes

## Design

The app is a monorepo: a FastAPI service owns all business rules, PostgreSQL owns durable state, and the React UI is a client of `/health` and `/api/v1`. Nginx (in Compose) and the Vite dev proxy keep the browser on the same origin as the API.

State that must survive a restart will live in PostgreSQL: users, episodes, requests, assignments, and status-history rows. The API process will stay stateless apart from the database connection.

Hard decisions so far:

1. **Same-origin HTTP, with an HttpOnly session cookie planned.** The brief allows either a cookie or a bearer token. A cookie set by the API and stored by the browser avoids putting a token in `localStorage`. State-changing requests will later send a CSRF header. `Secure` will be set when the app is served over HTTPS. Bearer tokens were the alternative; they are easier to test with `curl`, but a copied token in a browser store is the failure mode I want to avoid for an internal app that handles client deliveries.
2. **`/health` does not check the database.** It only reports that the process can answer. The API loads `DATABASE_URL` into configuration and does not open a connection. A database check belongs on a later readiness probe so a migration failure does not look like a dead process.
3. **Versioned routes under `/api/v1`, health at the root.** The UI contract stays stable if internal routes change.

The CSV header is `episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality`. The clean generator uses the same columns and ids shaped like `EP-100000`. I stored that export id in `episodes.source_episode_id` and used a separate numeric `episodes.id` for foreign keys. The unique constraint is case-sensitive text, so `EP-00003` and `ep-00003` are different until import decides otherwise. I did not add a robot allow-list: the export contains `arm-99`, and whether to keep it is an import rule.

`recorded_at` is `timestamptz`. Almost every seed timestamp has no offset; one row ends in `Z`. Import, which is not written yet, will treat naive values as UTC. `duration_seconds` is an integer because the clean generator writes integers. Roles, quality, and request status are PostgreSQL `CHECK` constraints fed by Python enums, not native enum types, so a new value is an ordinary migration.

An episode has at most one assignment row (`assignments.episode_id` is unique). That is enough for "one active request" without keeping assignment history. Requests live in `dataset_requests` so the table name is not the SQL-looking word `requests`. `deadline` is a date.

How duplicate CSV rows, blank fields, and `arm-99` are skipped is still an import decision.

## Left out

Auth, request endpoints, episode import, analytics, and the operator UI are not built. The schema and `/health` are.

With two more days after the required features, I would add the optional background export job only if the required acceptance checks were already green.

## What went wrong

Nothing has failed in this step yet.

## Security

Not implemented yet. The intended controls are hashed passwords (never the plaintext from `seed/users.json`), server-side role checks on every protected route, HttpOnly and SameSite cookies, CSRF protection on writes, and validation at the API boundary plus database constraints.

The two risks I expect to matter most once the domain exists: a client reading or accepting another client's request (broken object-level authorization), and a replayed or forged status change (missing CSRF or a transition checked only in the UI).

## Scale

Not exercised yet. Analytics will be SQL aggregations. The first likely limit at 100× episodes is an import or analytics query that scans `episodes` without an index on `recorded_at`, `robot_id`, and `quality`.

## AI tooling

Cursor's agent (Grok 4.7) inspected the seed files and drafted this scaffold. I reviewed the layout, the health contract, and the log fields against the brief before committing.
