"""DATA-01: `alembic upgrade head` creates every table, `alembic downgrade base` removes
them, and the app's session and health check work on the migrated Postgres.

Needs an EMPTY, throwaway Postgres in TEST_DATABASE_URL (CI starts one); the tests
drop every table in it. Skipped without it. Never point it at a database you need.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine, inspect, text

from app import config
from app.config import REPO_ROOT
from app.db import engine as app_engine
from app.db.engine import sqlalchemy_url

URL = os.environ.get("TEST_DATABASE_URL", "").strip()
pytestmark = pytest.mark.skipif(not URL, reason="TEST_DATABASE_URL is not set")

# plan.md, DATA-01.
REQUIRED_TABLES = {
    "universities",
    "terms",
    "courses",
    "sections",
    "meetings",
    "professors",
    "professor_sources",
    "students",
    "audits",
    "constraints",
    "favorites",
    "chats",
    "llm_cache",
}
# Catalog, schedule and professor tables with their own non-null university_id.
# course_requisites, meetings and section_instructors reach it through their parent row.
UNIVERSITY_TABLES = {
    "scrape_runs",
    "terms",
    "courses",
    "sections",
    "professors",
    "professor_sources",
}


def alembic(*args: str) -> None:
    subprocess.run(
        [sys.executable, "-m", "alembic", *args],
        cwd=REPO_ROOT,
        env={**os.environ, "DATABASE_URL": URL},
        check=True,
    )


@pytest.fixture(scope="module")
def db() -> Iterator[Engine]:
    eng = create_engine(sqlalchemy_url(URL))
    alembic("downgrade", "base")  # start clean, even after an interrupted run
    yield eng
    eng.dispose()


def _tables(eng: Engine) -> set[str]:
    return set(inspect(eng).get_table_names()) - {"alembic_version"}


def test_upgrade_creates_every_table(db: Engine) -> None:
    alembic("upgrade", "head")
    tables = _tables(db)
    assert REQUIRED_TABLES <= tables, REQUIRED_TABLES - tables


def test_catalog_tables_have_a_non_null_university_id(db: Engine) -> None:
    alembic("upgrade", "head")
    for table in UNIVERSITY_TABLES:
        columns = {c["name"]: c for c in inspect(db).get_columns(table)}
        assert "university_id" in columns, table
        assert columns["university_id"]["nullable"] is False, table


def test_downgrade_removes_every_table_and_upgrade_works_again(db: Engine) -> None:
    alembic("upgrade", "head")
    alembic("downgrade", "base")
    assert _tables(db) == set()
    alembic("upgrade", "head")
    assert REQUIRED_TABLES <= _tables(db)


@pytest.fixture
def app_on_postgres(db: Engine, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    alembic("upgrade", "head")
    monkeypatch.setattr(config, "DATABASE_URL", URL)
    app_engine.engine.cache_clear()
    yield
    app_engine.engine().dispose()
    app_engine.engine.cache_clear()


def test_session_reaches_the_same_students_row(db: Engine, app_on_postgres: None) -> None:
    from app.main import app

    client = TestClient(app, base_url="https://testserver")
    first = client.post("/api/session", json={"consent": True})
    assert "sid" in first.headers["set-cookie"]
    second = client.post("/api/session", json={"consent": True})
    student_id = first.json()["student"]["id"]
    assert second.json()["student"]["id"] == student_id
    with db.connect() as conn:
        rows = conn.execute(
            text("SELECT consented_at FROM students WHERE id = :id"), {"id": student_id}
        ).all()
    assert len(rows) == 1
    assert rows[0].consented_at is not None


def test_health_is_ok_on_postgres(app_on_postgres: None) -> None:
    from app.main import app

    res = TestClient(app).get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok"}
