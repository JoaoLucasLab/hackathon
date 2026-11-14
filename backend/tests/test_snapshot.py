"""DATA-06: `make snapshot` writes the catalog, sections and professors and no student
data; `make restore-snapshot` on an empty database gives the same row counts.

The file-format tests run everywhere. The round trip needs an EMPTY, throwaway
Postgres in TEST_DATABASE_URL (like test_migrations.py) and drops every table in it.
"""

from __future__ import annotations

import io
import os
import subprocess
import sys
from collections.abc import Iterator

import psycopg
import pytest

from app import config
from app.config import REPO_ROOT
from app.db import snapshot

URL = os.environ.get("TEST_DATABASE_URL", "").strip()
needs_postgres = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")

HEADER = b"".join(f"-- rows {t} 0\n".encode() for t in snapshot.TABLES)


def test_no_student_table_is_snapshotted() -> None:
    assert not set(snapshot.TABLES) & snapshot.STUDENT_TABLES


def test_restore_refuses_a_student_table_even_as_a_temp_table() -> None:
    lines = io.BytesIO(
        HEADER + b'COPY "snapshot_audits" ("id") FROM stdin;\n1\n\\.\n'
    ).readlines()
    with pytest.raises(SystemExit, match="unexpected table: snapshot_audits"):
        list(snapshot.statements(lines))


def test_restore_refuses_a_student_table() -> None:
    lines = io.BytesIO(
        HEADER + b"COPY students (id) FROM stdin;\n00000000-0000-0000-0000-000000000000\n\\.\n"
    ).readlines()
    with pytest.raises(SystemExit, match="unexpected table: students"):
        list(snapshot.statements(lines))


def test_restore_refuses_a_file_without_row_counts() -> None:
    with pytest.raises(SystemExit, match="not a demo snapshot"):
        snapshot.restore([b"-- something else\n", b"SELECT 1;\n"])


def test_statements_split_sql_and_copy_data() -> None:
    lines = io.BytesIO(
        HEADER
        + b"BEGIN;\nTRUNCATE universities;\n"
        + b'COPY "universities" ("id", "short_code") FROM stdin;\n1\tbyui\n2\tother\n\\.\n'
        + b"COMMIT;\n"
    ).readlines()
    assert list(snapshot.statements(lines)) == [
        ("TRUNCATE universities;", None),
        ('COPY "universities" ("id", "short_code") FROM stdin;', b"1\tbyui\n2\tother\n"),
    ]
    assert snapshot.expected_counts(lines) == dict.fromkeys(snapshot.TABLES, 0)


# --- Round trip on Postgres ------------------------------------------------------------

SEED = """
INSERT INTO universities (short_code, name) VALUES ('byui', 'BYU-Idaho');
INSERT INTO terms (university_id, code, block_kind) VALUES (1, '2027;WI', 'full');
INSERT INTO courses (university_id, code, title, department, catalog_year)
    VALUES (1, 'CSE 111', 'Programming with Functions', 'Computer Science', '2026-2027'),
           (1, 'CSE 210', 'Programming with Classes', 'Computer Science', '2026-2027');
INSERT INTO course_requisites (course_id, position, requisite_type, text)
    VALUES (2, 0, 'Course Prerequisite', 'CSE 111');
INSERT INTO sections (university_id, term_id, course_id, section, credits, source_url)
    VALUES (1, 1, 1, '01', 2, 'https://example.test/s/1'),
           (1, 1, 2, '01', 2, 'https://example.test/s/2');
INSERT INTO meetings (section_id, position, start_date, end_date)
    VALUES (1, 0, '2027-01-05', '2027-04-10');
INSERT INTO professors (university_id, full_name, department)
    VALUES (1, 'Example, Pat', 'Computer Science');
INSERT INTO section_instructors (section_id, professor_id, position) VALUES (1, 1, 0);
INSERT INTO professor_sources (university_id, professor_id, kind, value, source_url, fetched_at)
    VALUES (1, 1, 'biography', 'Teaches with "quotes",\ttabs and a \\ backslash.',
            'https://example.test/p/1', now());
INSERT INTO llm_cache (key, namespace, model, value)
    VALUES ('topic_tags:abc', 'topic_tags', 'test-model', '["python"]');
INSERT INTO students (id) VALUES ('00000000-0000-0000-0000-000000000001');
INSERT INTO audits (student_id, audit_encrypted)
    VALUES ('00000000-0000-0000-0000-000000000001', '\\x00');
"""


def _alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": URL},
        check=True,
    )


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection]:
    monkeypatch.setattr(config, "DATABASE_URL", URL)
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    with psycopg.connect(URL, autocommit=True) as conn:
        yield conn
    _alembic("downgrade", "base")


@needs_postgres
def test_round_trip_on_an_empty_database(db: psycopg.Connection) -> None:
    db.execute(SEED.encode())
    before = snapshot.row_counts(db)
    assert before["sections"] == 2 and before["professors"] == 1

    out = io.BytesIO()
    assert snapshot.write(out) == before
    data = out.getvalue()
    assert b"COPY students" not in data and b"COPY audits" not in data
    assert b"-- Catalog year: 2026-2027" in data

    # An empty database: the tables only (`make restore-snapshot` runs the migrations).
    _alembic("downgrade", "base")
    _alembic("upgrade", "head")
    assert snapshot.restore(io.BytesIO(data).readlines()) == before
    assert snapshot.row_counts(db) == before
    bio = db.execute("SELECT value FROM professor_sources").fetchone()
    assert bio == ('Teaches with "quotes",\ttabs and a \\ backslash.',)
    assert db.execute("SELECT count(*) FROM students").fetchone() == (0,)
    # Identity sequences continue after the restored ids.
    db.execute("INSERT INTO universities (short_code, name) VALUES ('other', 'Other')")


@needs_postgres
def test_restore_replaces_the_catalog_and_keeps_students(db: psycopg.Connection) -> None:
    db.execute(SEED.encode())
    out = io.BytesIO()
    snapshot.write(out)
    db.execute("UPDATE courses SET title = 'changed'")
    # A topic tag cached after the snapshot was written: kept, not thrown away.
    db.execute(
        "INSERT INTO llm_cache (key, namespace, model, value) "
        "VALUES ('topic_tags:newer', 'topic_tags', 'test-model', '[\"sql\"]')"
    )
    snapshot.restore(io.BytesIO(out.getvalue()).readlines())
    keys = {r[0] for r in db.execute("SELECT key FROM llm_cache").fetchall()}
    assert keys == {"topic_tags:abc", "topic_tags:newer"}
    titles = {r[0] for r in db.execute("SELECT title FROM courses").fetchall()}
    assert "changed" not in titles
    assert db.execute("SELECT count(*) FROM students").fetchone() == (1,)
    assert db.execute("SELECT count(*) FROM audits").fetchone() == (1,)


@needs_postgres
def test_a_wrong_row_count_restores_nothing(db: psycopg.Connection) -> None:
    db.execute(SEED.encode())
    out = io.BytesIO()
    snapshot.write(out)
    tampered = out.getvalue().replace(b"-- rows sections 2", b"-- rows sections 3")
    with pytest.raises(SystemExit, match="row counts differ"):
        snapshot.restore(io.BytesIO(tampered).readlines())
    assert db.execute("SELECT count(*) FROM sections").fetchone() == (2,)
