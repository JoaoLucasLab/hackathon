# Local database: setup and data

How to run the Postgres database in Docker, create its tables and fill it with
the Winter 2027 class schedule. Run every command from the repository root.

To run the whole app (database, backend and frontend) in Docker, as on the WSL
backup host, see `deploy/wsl/README.md`.

## What you need

- Docker Desktop, running
- Python 3.12 or newer, with the backend's packages installed once:
  `pip install -e ".[dev]"` (`data_cleaner.py` uses the backend's time parser)

## 1. Start the database

The user, password, database name and port live in `backend/.env`,
which is not in git. Create it once from the example and set your own password:

```bash
cp backend/.env.example backend/.env
```

Then start Postgres:

```bash
docker compose --env-file backend/.env -f backend/compose/compose.yaml up -d
```

This starts Postgres 18 in a container named `my-postgres-myplan`. The data
lives in a Docker volume, so it survives restarts.

| Setting  | Value                                         |
| -------- | --------------------------------------------- |
| Host     | `localhost`                                   |
| Port     | `POSTGRES_PORT` in `.env` (default `5433`)    |
| Database | `POSTGRES_DB` in `.env` (`app_db`)            |
| User     | `POSTGRES_USER` in `.env` (`app_user`)        |
| Password | `POSTGRES_PASSWORD` in `.env`                 |

The password is set when the database is created the first time. Changing it
in `.env` later does not change it inside an existing database; to start over
with a new one, see "Stop or reset" below.

The commands in this guide use `app_user` and `app_db`. If you changed them in
`.env`, use your values instead (and pass `--user` / `--database` to
`populate_db.py`).

Use these to connect from a database tool (DBeaver, TablePlus, pgAdmin).

## 2. Create the tables

```bash
docker exec -i my-postgres-myplan psql -U app_user -d app_db -v ON_ERROR_STOP=1 < backend/app/db/schema.sql
```

It prints nothing when it works. Running it again is safe: tables that
already exist are skipped. Check that the 9 tables are there:

```bash
docker exec -it my-postgres-myplan psql -U app_user -d app_db -c "\dt"
```

## 3. Get the data

The loader reads `scripts/out/course_search_clean.json`. `scripts/out/` is not
in git, so either ask a teammate for that file and put it in `scripts/out/`,
or build it yourself:

```bash
python3 scripts/scrape_course_search.py   # downloads the class schedule, about 25 minutes
python3 scripts/data_cleaner.py           # adds prerequisite trees and class times, a few seconds
```

The scraper reads the public BYU-Idaho Course Search (no login), waits 2
seconds between requests, and covers the subjects in `SUBJECTS` at the top of
the script (CSE, CIT, MATH). Keep the terminal open and the computer awake: it
writes `course_search.json` only at the end. Run one copy at a time.

## 4. Fill the database

```bash
python3 scripts/populate_db.py
```

Every run **deletes all rows** in the 9 tables and loads the file again, so the
database always matches the latest file. Delete and load run in one
transaction: if anything fails, nothing changes and the old data stays.

It prints the row count of each table before and after. On an empty database,
with the current data:

```
  universities             0 ->     1 rows
  scrape_runs              0 ->     1 rows
  terms                    0 ->     3 rows
  courses                  0 ->    88 rows
  course_requisites        0 ->   303 rows
  sections                 0 ->   300 rows
  meetings                 0 ->   314 rows
  professors               0 ->   141 rows
  section_instructors      0 ->   295 rows
```

## 5. Check it

```bash
docker exec -it my-postgres-myplan psql -U app_user -d app_db -c "SELECT c.code, s.section, c.title, s.status_raw FROM sections s JOIN courses c ON c.id = s.course_id ORDER BY c.code, s.section LIMIT 10;"
```

## Update the data later

```bash
python3 scripts/scrape_course_search.py
python3 scripts/data_cleaner.py
python3 scripts/populate_db.py
```

## Stop or reset

```bash
docker compose --env-file backend/.env -f backend/compose/compose.yaml stop      # stop, keep the data
docker compose --env-file backend/.env -f backend/compose/compose.yaml down -v   # delete the container AND all data
```

After `down -v`, start again from step 1.

## Troubleshooting

| Problem | Fix |
| ------- | --- |
| `required variable POSTGRES_USER is missing a value` | `backend/.env` is missing, or `--env-file backend/.env` was left out of the command. See step 1. |
| `No such container: my-postgres-myplan` | The database is not running. Do step 1. |
| `relation "courses" does not exist` | The tables were not created. Do step 2. |
| `FileNotFoundError: ... course_search_clean.json` | Do step 3. |
| `psql failed. Nothing changed ...` | The message under it is Postgres's error. The old data is untouched; fix the file and run step 4 again. |
| `cannot truncate a table referenced in a foreign key constraint` | Another table now points at these tables (for example student favorites). The full refresh stops on purpose so it never deletes that data; talk to the Data owner. |
| Port 5433 already in use | Another program uses it. Set another `POSTGRES_PORT` in `.env`, run step 1 again, and use that port in your database tool. |
