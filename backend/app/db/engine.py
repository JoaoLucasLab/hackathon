"""The app's database connection (SQLAlchemy 2, psycopg 3).

`DATABASE_URL` is a plain `postgresql://` URL on every host (Neon, the compose
files); the driver is picked here, never in the URL. Without `DATABASE_URL`
(local dev without Docker, tests) students and sessions live in an in-memory
SQLite database that is lost when the process stops. Nothing is written to disk.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app import config
from app.db.models import Base


def sqlalchemy_url(url: str) -> str:
    """`postgresql://` or `postgres://` -> `postgresql+psycopg://`. Other URLs are kept."""
    for prefix in ("postgresql://", "postgres://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


@lru_cache(maxsize=1)
def engine() -> Engine:
    if config.DATABASE_URL:
        return create_engine(
            sqlalchemy_url(config.DATABASE_URL),
            pool_pre_ping=True,  # Neon closes idle connections
            connect_args={"connect_timeout": 10},
        )
    memory = create_engine(
        "sqlite+pysqlite:///:memory:",
        poolclass=StaticPool,  # one connection, so every request sees the same tables
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(memory)
    return memory


def session() -> Session:
    return Session(engine(), expire_on_commit=False)


def ping() -> Literal["ok", "not_configured", "error"]:
    """`ok` when the database answers `SELECT 1`; `not_configured` without DATABASE_URL."""
    if not config.DATABASE_URL:
        return "not_configured"
    try:
        with engine().connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return "error"
    return "ok"
