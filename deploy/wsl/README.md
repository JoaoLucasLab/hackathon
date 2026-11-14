# Backup hosting: WSL server + Docker + Tailscale Funnel

Render (frontend, backend) and Neon (Postgres) are the primary hosting
(`plan.md`, "Hosting"). This folder is the backup: the same app in three Docker
containers on a private WSL server, published through Tailscale.

```
Browser ──https──> Tailscale Funnel :443 ──> 127.0.0.1:8080  web (nginx)
                                                 ├─ /            built React app
                                                 └─ /api /admin /health /docs ──> backend:8000
Teammate (tailnet) ──> Tailscale Serve tcp :5432 ──> 127.0.0.1:5433  db (Postgres 18)
Optional: Funnel :8443 ──> 127.0.0.1:8000 backend directly
```

The browser sees one origin, so there is no CORS and the session cookie is
first-party. The database is reachable only from devices in the tailnet, never
from the public internet.

## One-time setup on the server

1. WSL 2 with Docker Engine (or Docker Desktop with WSL integration) and
   `docker compose`.
2. Tailscale installed **inside the WSL distro** and logged in
   (`sudo tailscale up`). If Tailscale runs on the Windows host instead, run the
   `tailscale` commands from `funnel.sh` in Windows; WSL's localhost forwarding
   makes the 127.0.0.1 ports reachable there.
3. In the Tailscale admin console: enable MagicDNS and HTTPS certificates, and
   allow Funnel for this machine (the `funnel` node attribute in the tailnet
   policy). `tailscale funnel` prints a link to fix this if it is missing.
4. Copy the repo there once (or use `push.sh` below), then create the env file:

   ```bash
   cp deploy/wsl/.env.example deploy/wsl/.env
   # set PUBLIC_URL, POSTGRES_PASSWORD, ANTHROPIC_API_KEY, DATA_KEY, SESSION_SECRET
   ```

   `PUBLIC_URL` is `https://<machine-name>.<tailnet>.ts.net` (see
   `tailscale status --json | jq -r .Self.DNSName`, without the final dot).

## Deploy or update

From your laptop (builds the images on the server, so arm64 Mac to amd64 WSL works):

```bash
deploy/wsl/push.sh user@server            # rsync to ~/course-planner, then compose up --build
```

Or on the server itself:

```bash
docker compose -f deploy/wsl/compose.yaml --env-file deploy/wsl/.env up -d --build
```

Then publish it (once; the rules survive restarts):

```bash
deploy/wsl/funnel.sh up        # add `api` to also expose the backend on :8443
deploy/wsl/funnel.sh status
```

If the server's Funnel already forwards to a fixed local port (for example
`/ -> http://127.0.0.1:8000`), skip `funnel.sh` and put the `web` container on that
port instead: `WEB_HOST_PORT=8000` and `API_HOST_PORT=8001` in `deploy/wsl/.env`.
`web` serves the app and proxies the API, so one forwarded port covers both.

Check: `https://<machine>.<tailnet>.ts.net/` loads the app and
`https://<machine>.<tailnet>.ts.net/openapi.json` (later `/health`) answers.

## Database

- On the first start of an empty volume, Postgres runs `backend/app/db/schema.sql`.
- Load the schedule data (needs `scripts/out/course_search_clean.json` on the
  server; `push.sh` does not upload `scripts/out/`, copy it by hand):

  ```bash
  python3 scripts/populate_db.py --container course-planner-db
  ```

- Connect from a teammate's machine in the tailnet:
  host `<machine>.<tailnet>.ts.net`, port `5432`, user/db from `.env`.

### Migrations

When DATA-01 adds Alembic, run migrations inside the backend container:

```bash
docker compose -f deploy/wsl/compose.yaml --env-file deploy/wsl/.env exec backend alembic upgrade head
```

and remove the `schema.sql` init mount from `compose.yaml` in the same PR.

## Stop, reset, logs

```bash
C="docker compose -f deploy/wsl/compose.yaml --env-file deploy/wsl/.env"
$C logs -f backend
$C stop                  # stop, keep data
$C down -v               # delete containers AND the database volume
deploy/wsl/funnel.sh down
```

## Troubleshooting

| Problem | Fix |
| --- | --- |
| `Funnel not available` / link to the admin console | Step 3: enable HTTPS and the `funnel` node attribute. |
| App loads, chat never streams | Something buffers SSE. The nginx `/api` block must keep `proxy_buffering off`. |
| 502 from nginx | Backend is down: `$C logs backend`. |
| `required variable ... is missing` | `deploy/wsl/.env` is missing or `--env-file` was left out. |
| `tailscale: permission denied` | `TAILSCALE="sudo tailscale" deploy/wsl/funnel.sh up`, or `sudo tailscale set --operator=$USER`. |
