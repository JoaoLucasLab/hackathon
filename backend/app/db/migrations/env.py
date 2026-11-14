"""Alembic environment. The database comes from DATABASE_URL, a plain postgresql:// URL;
the driver is picked by app.db.engine.sqlalchemy_url, as in the app.

Migrations are written by hand (no autogenerate): raw SQL, so the tables match what
scripts/populate_db.py and app/api/catalog_data.py expect, column for column.
"""

from __future__ import annotations

import os

from alembic import context
from sqlalchemy import create_engine

from app.db.engine import sqlalchemy_url

url = os.environ.get("DATABASE_URL", "").strip()
if not url:
    raise SystemExit("DATABASE_URL is not set (make migrate reads it from backend/.env)")


def run_migrations_online() -> None:
    connectable = create_engine(sqlalchemy_url(url), connect_args={"connect_timeout": 10})
    with connectable.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise SystemExit("Offline (--sql) mode is not supported; run against a database.")
run_migrations_online()
