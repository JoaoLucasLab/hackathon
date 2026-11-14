"""SQLAlchemy models for the tables the app itself reads and writes.

The tables are created by the Alembic migrations in `migrations/`, not from these
models (except the in-memory database of `engine.py`). Keep both in step.
Catalog and schedule tables are loaded by scripts/populate_db.py and read with
plain SQL in app/api/catalog_data.py, so they have no model here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Dialect, Text, TypeDecorator, Uuid
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _now() -> datetime:
    return datetime.now(UTC)


class UtcDateTime(TypeDecorator[datetime]):
    """`timestamptz`. Always read back as UTC-aware, also from the in-memory SQLite
    of engine.py, which drops the time zone."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value


class Base(DeclarativeBase):
    pass


class Student(Base):
    """One anonymous session. No name, email, password or BYU-Idaho ID number, ever."""

    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    consented_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    track: Mapped[str | None] = mapped_column(Text)
    catalog_year: Mapped[str | None] = mapped_column(Text)
