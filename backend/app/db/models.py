"""SQLAlchemy models for the tables the app itself reads and writes.

The tables are created by the Alembic migrations in `migrations/`, not from these
models (except the in-memory database of `engine.py`). Keep both in step.
Catalog and schedule tables are loaded by scripts/populate_db.py and read with
plain SQL in app/api/catalog_data.py, so they have no model here.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    DateTime,
    Dialect,
    ForeignKey,
    Integer,
    LargeBinary,
    Text,
    TypeDecorator,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
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


# `bigint GENERATED ALWAYS AS IDENTITY` on Postgres; SQLite only autoincrements INTEGER.
_Id = BigInteger().with_variant(Integer(), "sqlite")
_Json = JSON().with_variant(JSONB(), "postgresql")


def _student_fk() -> Any:
    return ForeignKey("students.id", ondelete="CASCADE")


class Student(Base):
    """One anonymous session. No name, email, password or BYU-Idaho ID number, ever."""

    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    last_seen_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
    consented_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    track: Mapped[str | None] = mapped_column(Text)
    catalog_year: Mapped[str | None] = mapped_column(Text)


class Audit(Base):
    """A confirmed DegreeAudit as JSON encrypted with DATA_KEY (app/db/crypto.py).
    Never the PDF, a name or an ID number. The newest row is the current audit."""

    __tablename__ = "audits"

    id: Mapped[int] = mapped_column(_Id, primary_key=True, autoincrement=True)
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, _student_fk())
    audit_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    confirmed_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class Constraints(Base):
    """The ConstraintSet behind the chips, one per student."""

    __tablename__ = "constraints"

    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, _student_fk(), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(_Json)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class Favorite(Base):
    __tablename__ = "favorites"

    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, _student_fk(), primary_key=True)
    professor_id: Mapped[str] = mapped_column(Text, primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)


class Chat(Base):
    """One chat message (a ChatTurn as JSON), encrypted with DATA_KEY."""

    __tablename__ = "chats"

    id: Mapped[int] = mapped_column(_Id, primary_key=True, autoincrement=True)
    student_id: Mapped[uuid.UUID] = mapped_column(Uuid, _student_fk())
    role: Mapped[str] = mapped_column(Text)  # 'user' or 'assistant'
    message_encrypted: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime, default=_now)
