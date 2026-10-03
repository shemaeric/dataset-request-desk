# Notes

## Design

Postgres holds the durable state: users, sessions, episodes, requests, assignments, and status history. The API process is stateless apart from its connection pool. The React app is a client of `/health` and `/api/v1`. Nginx in Compose, and the Vite proxy in local dev, keep the browser on the same origin as the API.

An episode's export id is `episodes.source_episode_id`, unique, and stored uppercased. `episodes.id` is the numeric key other tables use. A request lives in `dataset_requests` and belongs to one client. Each status change appends `request_status_history` with the actor and the time, in the same transaction as the status column. An assignment is one row per episode (`assignments.episode_id` is unique). A session row stores the SHA-256 of the cookie token, not the token.

Three choices took the longest.

I used an HttpOnly session cookie plus a CSRF header. A bearer token is easier to call with `curl`, and a copied token in `localStorage` is a bad fit for an internal app that accepts and rejects client deliveries. The CSRF cookie is readable by the page so the client can echo it. `SameSite=Lax` covers ordinary cross-site posts. Login is the one unsafe route that does not require the header.

A client who asks for another client's request gets the same 404 as a missing id. A 403 would tell them the id exists. Staff still get 403 when they can see the request but do not own that workflow step.

An assignment stays after delivery, acceptance, and rejection. Removing it is a separate staff action, and only while the request is `in_progress`. The unique episode id is what stops two requests from taking the same episode, including two requests that arrive together. Import keeps the first valid row for an id. An identical repeat is skipped. A different repeat is reported and does not overwrite the stored row.

`/health` does not query Postgres. A failed migration should not look like a dead process. Readiness is "Compose started the API only after migrate exited 0."

## Left out

CSV import and analytics are staff API routes. The UI does not upload a file, and it does not draw the analytics figures. Operators filter the episode list by task and quality and assign from that list. I skipped live updates and the background export job. Deployment was the stretch item.

An operator or admin imports episodes with `POST /api/v1/episodes/import`. The body is multipart, field name `file`. Call it on the same origin as the UI (nginx proxies `/api/`), after login, and send the CSRF cookie back as `X-CSRF-Token`. From the repo directory, against the default Compose UI port:

```bash
curl -sS -c /tmp/desk.cookies -H 'Content-Type: application/json' \
  -d '{"email":"ops1@example.com","password":"ops123"}' \
  http://127.0.0.1:8080/api/v1/auth/login

csrf=$(awk '$6=="desk_csrf" {print $7}' /tmp/desk.cookies)

curl -sS -b /tmp/desk.cookies -H "X-CSRF-Token: $csrf" \
  -F "file=@seed/episodes.csv" \
  http://127.0.0.1:8080/api/v1/episodes/import
```

Use the published web port when it is not 8080. The public host is `8081`. The JSON body reports `created`, `skipped`, `conflicts`, and `invalid`. Running the same file again skips rows that are already stored.

With two more days I would polish the UI, put a name and TLS in front of the public host, publish Postgres on `127.0.0.1` only, replace the fixture passwords, and batch the importer.

## What went wrong

The first `docker compose up -d --build` on the VPS built the images, then the `db` container died with `Bind for 0.0.0.0:5432 failed: port is already allocated`. The web container then failed the same way on 8080. `ss` showed both ports already taken by other processes on that machine. I left those processes up and set `POSTGRES_PORT=5433` and `WEB_PORT=8081` in `.env`. I did not change the port inside `DATABASE_URL`. That URL is used on the Compose network, where Postgres still listens on 5432 and the hostname is `db`. After that, `curl` to `/health` on the web port returned `{"status":"ok"}`.

## Security

Passwords are Argon2. An unknown email, a bad password, and an inactive user all get `Invalid email or password`. Deactivating a user sets `is_active` false, which login and an existing session both honor. The role comes from the user row, not from the login body. Request bodies are checked with Pydantic: task length, episode count, deadline window, note length, email shape. The CSV path rejects a non-UTF-8 file, a file over 32MB, and a bad header before any insert. Bad rows are reported and the valid rows around them are kept. A patch that would leave no active admin is rejected.

The two issues I would worry about on a desk like this:

The fixture passwords are real logins, and this copy is on a public IP. Postgres is also published on a host port. Docker punches past `ufw` for published ports, so closing the firewall in the OS is not enough. I would change the seed passwords, keep `.env` off the host's public interface, and bind the database to localhost.

The CSRF token has to be readable by the page. A script injected into a task name or a note can then send the same writes the user can send. I treat that as the main XSS consequence, and I would rather escape those fields in the UI than move to a bearer token to "avoid CSRF."

## Scale

At 10× users the first limit is one synchronous API process. Every request checks the session in Postgres, and a CSV import holds that worker until the file is done. I would size the pool before adding workers, and I would take import off the request path.

At 100× episodes the importer, one row at a time, is the part I would change first. The day/robot aggregate can use `ix_episodes_recorded_at_robot_id`. The top-task query filters `recorded_at` and `quality` together, and that is the plan I would `EXPLAIN` before adding an index. The analytics window is capped at 366 days so one call cannot scan an open-ended range.

## AI tooling

I used Claude Code occasionally, to look something up or to check a diff. I kept a suggestion only after I had tried it myself.
