#!/bin/sh
# Writes or restores the demo snapshot (DATA-06). Run from anywhere:
#   scripts/snapshot.sh write   [PATH]    # make snapshot
#   scripts/snapshot.sh restore [PATH]    # make restore-snapshot (after `make migrate`)
# PATH defaults to snapshots/demo.sql.gz. The database is DATABASE_URL.
# The code is backend/app/db/snapshot.py, so it also runs in the backend image. The
# backend does not start on a database without sections, so on a new database use a
# one-off container (`run`, not `exec`):
#   docker compose ... run --rm -T backend alembic upgrade head
#   docker compose ... run --rm -T backend python -m app.db.snapshot restore - < snapshots/demo.sql.gz
set -eu
cd "$(dirname "$0")/.."
PYTHONPATH=backend exec "${PYTHON:-python3}" -m app.db.snapshot "$@"
