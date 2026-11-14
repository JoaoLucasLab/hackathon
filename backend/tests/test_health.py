"""DATA-01: GET /health says whether the app is up and can reach its database.

The `{"status": "ok", "db": "ok"}` answer on a real Postgres is checked in
test_migrations.py (it needs TEST_DATABASE_URL).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import config
from app.db import engine
from app.main import app

client = TestClient(app)


def test_health_without_a_database_is_up_but_says_so() -> None:
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "not_configured"}


def test_health_with_the_database_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "ping", lambda: "ok")
    res = client.get("/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok", "db": "ok"}


def test_health_with_the_database_down_is_503(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(engine, "ping", lambda: "error")
    res = client.get("/health")
    assert res.status_code == 503
    assert res.json() == {"status": "error", "db": "error"}


def test_ping_reports_an_unreachable_database(monkeypatch: pytest.MonkeyPatch) -> None:
    # Port 1 on localhost refuses the connection at once.
    monkeypatch.setattr(config, "DATABASE_URL", "postgresql://u:p@127.0.0.1:1/db")
    engine.engine.cache_clear()
    try:
        assert engine.ping() == "error"
    finally:
        engine.engine.cache_clear()


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("postgresql://u:p@h/db?sslmode=require", "postgresql+psycopg://u:p@h/db?sslmode=require"),
        ("postgres://u:p@h:5432/db", "postgresql+psycopg://u:p@h:5432/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
    ],
)
def test_plain_postgres_urls_get_the_psycopg_driver(url: str, expected: str) -> None:
    assert engine.sqlalchemy_url(url) == expected

