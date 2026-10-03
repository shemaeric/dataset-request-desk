# Notes

## Design

The app is a monorepo: a FastAPI service owns all business rules, PostgreSQL owns durable state, and the React UI is a client of `/health` and `/api/v1`. Nginx (in Compose) and the Vite dev proxy keep the browser on the same origin as the API.

State that must survive a restart will live in PostgreSQL: users, episodes, requests, assignments, and status-history rows. The API process will stay stateless apart from the database connection.

Hard decisions so far:

1. **Same-origin HTTP, with an HttpOnly session cookie planned.** The brief allows either a cookie or a bearer token. A cookie set by the API and stored by the browser avoids putting a token in `localStorage`. State-changing requests will later send a CSRF header. `Secure` will be set when the app is served over HTTPS. Bearer tokens were the alternative; they are easier to test with `curl`, but a copied token in a browser store is the failure mode I want to avoid for an internal app that handles client deliveries.
2. **`/health` does not check the database.** It only reports that the process can answer. Compose already waits on Postgres before starting the API. A database check belongs on a later readiness probe so a migration failure does not look like a dead process.
3. **Versioned routes under `/api/v1`, health at the root.** The UI contract stays stable if internal routes change.

Import rules, the exact request schema, and how duplicate CSV rows are resolved are not decided yet. They will be written down when those features land.

The provided `seed/episodes.csv` (190 data rows) is messy in ways the importer will have to classify: duplicate `episode_id`s (`EP-00011` with different quality, `EP-00030` and `EP-00074` repeated), a blank id, a missing robot, unknown robot `arm-99`, padded robot ids, mixed task-name case, several timestamp shapes, non-integer or empty durations, quality values outside `good` / `usable` / `bad`, a short row (`EP-90001`), and `ep-00003` differing only by case from `EP-00003`.

## Left out

This step is the process skeleton only: Compose, `/health`, request logging, and a page that shows the health result. No auth, schema, workflow, import, analytics, or operator UI yet.

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
