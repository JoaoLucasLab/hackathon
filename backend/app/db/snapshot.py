"""The demo snapshot (DATA-06): `make snapshot` / `make restore-snapshot`.

    python -m app.db.snapshot write   [PATH]    # default snapshots/demo.sql.gz
    python -m app.db.snapshot restore [PATH]    # PATH '-' reads stdin

The snapshot holds the catalog, schedule and professor tables (and the topic tags in
llm_cache), never a student table. It is gzipped plain SQL, the same COPY format as
pg_dump, so `gunzip -c snapshots/demo.sql.gz | psql "$DATABASE_URL"` also restores it.
It is written with psycopg instead of pg_dump, so it needs no Postgres client tools
(the backend image has none) and works with any server version.

Restore replaces those tables in one transaction and checks the row counts in the
file's header before it commits: a failed restore changes nothing. llm_cache is the
exception: its rows are added to the ones already there (a cached result never goes
stale, and replacing it would throw away paid Claude calls). The tables must exist
first (`alembic upgrade head`; the Makefile target runs it).
"""

from __future__ import annotations

import argparse
import gzip
import re
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import psycopg
from psycopg import sql

from app import config

DEFAULT_PATH = config.REPO_ROOT / "snapshots" / "demo.sql.gz"

# Parents before children, so the COPY blocks load in order.
TABLES = (
    "universities",
    "scrape_runs",
    "terms",
    "courses",
    "course_requisites",
    "sections",
    "meetings",
    "professors",
    "section_instructors",
    "professor_sources",
    "llm_cache",
)
# Merged into the target instead of replaced (see above). Loaded through a temporary
# table named snapshot_<table>.
MERGED = frozenset({"llm_cache"})
# Never in a snapshot (AGENTS.md, "Student privacy").
STUDENT_TABLES = frozenset({"students", "audits", "constraints", "favorites", "chats"})

_ROWS = re.compile(r"^-- rows (\w+) (\d+)$")
_COPY = re.compile(r'^COPY "?(\w+)"? \(.*\) FROM stdin;$')


class _Writable(Protocol):
    def write(self, data: bytes, /) -> int: ...


def _connect() -> psycopg.Connection:
    if not config.DATABASE_URL:
        raise SystemExit("DATABASE_URL is not set")
    return psycopg.connect(config.DATABASE_URL, connect_timeout=10)


def _columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND is_generated = 'NEVER' "
        "ORDER BY ordinal_position",
        (table,),
    ).fetchall()
    if not rows:
        raise SystemExit(f"table {table} does not exist: run `make migrate` first")
    return [r[0] for r in rows]


def _identity_columns(conn: psycopg.Connection, table: str) -> list[str]:
    rows = conn.execute(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = %s AND is_identity = 'YES'",
        (table,),
    ).fetchall()
    return [r[0] for r in rows]


def row_counts(conn: psycopg.Connection) -> dict[str, int]:
    counts: dict[str, int] = {}
    for table in TABLES:
        query = sql.SQL("SELECT count(*) FROM {}").format(sql.Identifier(table))
        row = conn.execute(query).fetchone()
        counts[table] = int(row[0]) if row else 0
    return counts


def _catalog_years(conn: psycopg.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT DISTINCT catalog_year FROM courses WHERE catalog_year IS NOT NULL ORDER BY 1"
    ).fetchall()
    return [r[0] for r in rows]


def write(out: _Writable) -> dict[str, int]:
    """Writes the snapshot SQL to `out` (uncompressed). Returns the row counts."""
    with _connect() as conn:
        # One consistent view of every table, even while a loader runs.
        conn.isolation_level = psycopg.IsolationLevel.REPEATABLE_READ
        conn.read_only = True
        counts = row_counts(conn)
        years = ", ".join(_catalog_years(conn)) or "unknown"

        def line(text: str = "") -> None:
            out.write(text.encode() + b"\n")

        line("-- Demo snapshot (DATA-06): catalog, schedule and professor tables. No student data.")
        line(f"-- Written {datetime.now(UTC).isoformat(timespec='seconds')}")
        line(f"-- Catalog year: {years}")
        for table, count in counts.items():
            line(f"-- rows {table} {count}")
        line("BEGIN;")
        line(f"TRUNCATE {', '.join(t for t in TABLES if t not in MERGED)};")
        cur = conn.cursor()
        for table in TABLES:
            columns = sql.SQL(", ").join(map(sql.Identifier, _columns(conn, table)))
            target = sql.Identifier(f"snapshot_{table}" if table in MERGED else table)
            if table in MERGED:
                temp = sql.SQL("CREATE TEMP TABLE {} (LIKE {}) ON COMMIT DROP;").format(
                    target, sql.Identifier(table)
                )
                line(temp.as_string(conn))
            copy_from = sql.SQL("COPY {} ({}) FROM stdin;").format(target, columns)
            line(copy_from.as_string(conn))
            copy_to = sql.SQL("COPY {} ({}) TO STDOUT").format(sql.Identifier(table), columns)
            with cur.copy(copy_to) as copy:
                for data in copy:
                    out.write(bytes(data))
            line("\\.")
            if table in MERGED:
                merge = sql.SQL(
                    "INSERT INTO {} ({}) SELECT {} FROM {} ON CONFLICT DO NOTHING;"
                ).format(sql.Identifier(table), columns, columns, target)
                line(merge.as_string(conn))
        for table in TABLES:
            for column in _identity_columns(conn, table):
                line(
                    f"SELECT setval(pg_get_serial_sequence('{table}', '{column}'), "
                    f"COALESCE(max({column}), 0) + 1, false) FROM {table};"
                )
        line("COMMIT;")
        conn.rollback()
    return counts


def expected_counts(lines: list[bytes]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw in lines:
        if not raw.startswith(b"--"):
            break
        match = _ROWS.match(raw.decode().rstrip("\n"))
        if match:
            counts[match[1]] = int(match[2])
    return counts


def statements(lines: list[bytes]) -> Iterator[tuple[str, bytes | None]]:
    """(SQL, COPY data or None) for each statement of a snapshot file. Comments and the
    file's BEGIN / COMMIT are skipped: restore runs everything in its own transaction."""
    it = iter(lines)
    for raw in it:
        text = raw.decode().rstrip("\n")
        if not text or text.startswith("--") or text in ("BEGIN;", "COMMIT;"):
            continue
        match = _COPY.match(text)
        if match:
            table = match[1].removeprefix("snapshot_")
            if table in STUDENT_TABLES or table not in TABLES:
                raise SystemExit(f"snapshot has an unexpected table: {match[1]}")
            data = bytearray()
            for row in it:
                if row == b"\\.\n":
                    break
                data += row
            else:
                raise SystemExit(f"snapshot ends inside the COPY of {match[1]}")
            yield text, bytes(data)
        else:
            yield text, None


def restore(lines: list[bytes]) -> dict[str, int]:
    """Replaces the snapshot's tables with its rows (merges llm_cache), in one
    transaction. Raises SystemExit (and changes nothing) when a row count differs from
    the header: a merged table may have more rows than the snapshot, never fewer."""
    expected = expected_counts(lines)
    if set(expected) != set(TABLES):
        raise SystemExit("not a demo snapshot: the header does not list every table's rows")
    with _connect() as conn:
        for table in TABLES:
            _columns(conn, table)  # the tables must exist (`make migrate`)
        cur = conn.cursor()
        for statement, data in statements(lines):
            if data is None:
                cur.execute(statement.encode())
            else:
                with cur.copy(statement.encode()) as copy:
                    copy.write(data)
        counts = row_counts(conn)
        short = {
            t: counts[t]
            for t in TABLES
            if counts[t] < expected[t] or (counts[t] != expected[t] and t not in MERGED)
        }
        if short:
            conn.rollback()
            raise SystemExit(f"row counts differ, nothing restored: {counts} != {expected}")
        conn.commit()
    return counts


def _read(path: str) -> list[bytes]:
    if path == "-":
        data = sys.stdin.buffer.read()
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        return data.splitlines(keepends=True)
    with gzip.open(path, "rb") as f:
        return f.readlines()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", choices=["write", "restore"])
    parser.add_argument("path", nargs="?", default=str(DEFAULT_PATH))
    args = parser.parse_args(argv)
    if args.action == "write":
        path = Path(args.path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        with gzip.open(tmp, "wb") as f:
            counts = write(f)
        tmp.replace(path)
        print(f"wrote {path}")
    else:
        counts = restore(_read(args.path))
        print(f"restored {args.path}")
    for table, count in counts.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
