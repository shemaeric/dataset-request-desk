# Notes

## Design

The app is a monorepo: a FastAPI service owns all business rules, PostgreSQL owns durable state, and the React UI is a client of `/health` and `/api/v1`. Nginx (in Compose) and the Vite dev proxy keep the browser on the same origin as the API.

State that must survive a restart will live in PostgreSQL: users, episodes, requests, assignments, and status-history rows. The API process will stay stateless apart from the database connection.

Hard decisions so far:

1. **Same-origin HTTP, with an HttpOnly session cookie planned.** The brief allows either a cookie or a bearer token. A cookie set by the API and stored by the browser avoids putting a token in `localStorage`. State-changing requests will later send a CSRF header. `Secure` will be set when the app is served over HTTPS. Bearer tokens were the alternative; they are easier to test with `curl`, but a copied token in a browser store is the failure mode I want to avoid for an internal app that handles client deliveries.
2. **`/health` does not check the database.** It only reports that the process can answer. The API loads `DATABASE_URL` into configuration and does not open a connection. A database check belongs on a later readiness probe so a migration failure does not look like a dead process.
3. **Versioned routes under `/api/v1`, health at the root.** The UI contract stays stable if internal routes change.

The CSV header is `episode_id,robot_id,task_name,recorded_at,duration_seconds,operator_name,quality`. The clean generator uses the same columns and ids shaped like `EP-100000`. I stored that export id in `episodes.source_episode_id` and used a separate numeric `episodes.id` for foreign keys. The unique constraint is case-sensitive text. Import uppercases the id first, so `ep-00003` is the same key as `EP-00003`.

`recorded_at` is `timestamptz`. Almost every seed timestamp has no offset; one row ends in `Z`. Import, which is not written yet, will treat naive values as UTC. `duration_seconds` is an integer because the clean generator writes integers. Roles, quality, and request status are PostgreSQL `CHECK` constraints fed by Python enums, not native enum types, so a new value is an ordinary migration.

An episode has at most one assignment row (`assignments.episode_id` is unique). That row stays until an operator removes it. Accepting or rejecting a request does not free the episode. Assign and remove are allowed only while the request is `in_progress`, and only for `good` or `usable` episodes. Those writes lock the request row, then the episode row. Delivery locks the request and counts assignment rows in that same transaction before it changes status. Requests live in `dataset_requests` so the table name is not the SQL-looking word `requests`. `deadline` is a date.

Import keeps the first valid row for an episode id. An identical repeat is skipped. A repeat with different fields is reported as a conflict and does not overwrite the stored row. `arm-99` is rejected because it is not one of the known robots; that list lives in the importer, not in a schema constraint. Blank lines are ignored. Other missing or unparseable fields are row errors, and the valid rows around them are still saved. Naive timestamps are UTC, and `14/08/2026` is day-first because the day is 14.

Request status changes go through one table: staff move `submitted` or `rejected` to `in_progress`, and `in_progress` to `delivered`; the owning client moves `delivered` to `accepted` or `rejected`. The status column and the history row commit together. `delivered` requires at least `episodes_requested` assignment rows. A client who asks for another client's id gets the same 404 as a missing id.

## Left out

Analytics and the operator UI are not built. Auth, the schema, requests, episode import, and assignment are.

With two more days after the required features, I would add the optional background export job only if the required acceptance checks were already green.

## What went wrong

Nothing has failed in this step yet.

## Security

Passwords are Argon2 hashes. Login failures use one message for an unknown email, a bad password, and an inactive user. The session cookie is HttpOnly and SameSite=Lax; the database stores only a hash of the token. A non-HttpOnly CSRF cookie must be echoed in `X-CSRF-Token` on later writes. `Secure` is off for local HTTP and on when `COOKIE_SECURE=true`. The role comes from the session user row, not from the login body.

A client who asks for another client's request gets the same 404 as a missing id, on detail and on transition. Status changes go through the transition table, and the status write is the same transaction as the history row. CSRF still covers those POSTs. Assignment is staff-only. A `bad` episode is rejected, and the unique episode constraint stops a second request from taking it. Delivery counts those rows while the request row is locked.

## Scale

Not exercised yet. Analytics will be SQL aggregations. The first likely limit at 100× episodes is an import or analytics query that scans `episodes` without an index on `recorded_at`, `robot_id`, and `quality`.

## AI tooling

Cursor's agent (Grok 4.7) inspected the seed files and drafted this scaffold. I reviewed the layout, the health contract, and the log fields against the brief before committing.
