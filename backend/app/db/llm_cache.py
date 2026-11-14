"""The ``llm_cache`` table: Claude results keyed by a SHA-256 of their input.

Implements the ``TagCache`` seam of app/llm/topic_tags.py. The prerequisite
fallback (ENG-04) still uses its in-memory cache and can move here later.
"""

from __future__ import annotations

import os

import psycopg
from psycopg.types.json import Jsonb


def _connect() -> psycopg.Connection:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("DATABASE_URL is not set")
    return psycopg.connect(url, connect_timeout=10)


class DbTagCache:
    def __init__(self, namespace: str = "topic_tags") -> None:
        self.namespace = namespace

    def get(self, key: str) -> list[str] | None:
        with _connect() as conn:
            row = conn.execute("SELECT value FROM llm_cache WHERE key = %s", (key,)).fetchone()
        return list(row[0]) if row else None

    def set(self, key: str, tags: list[str], *, subject: str | None, model: str) -> None:
        with _connect() as conn:
            conn.execute(
                "INSERT INTO llm_cache (key, namespace, subject, model, value) "
                "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (key) DO NOTHING",
                (key, self.namespace, subject, model, Jsonb(tags)),
            )
