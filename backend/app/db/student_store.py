"""Reads and writes the student tables (DATA-06): audits, chats, constraints, favorites.

Audit JSON and chat messages are encrypted here with DATA_KEY (app/db/crypto.py), so
no caller can store them in plain text. Callers pass JSON text and dicts, not
contract models: validating them is the API's job. Every function takes the student
id from the signed `sid` cookie (app/api/session.py).
"""

from __future__ import annotations

import logging
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import delete, select

from app.db import crypto, engine
from app.db.models import Audit, Chat, Constraints, Favorite, Student

log = logging.getLogger(__name__)

# Children first: the in-memory SQLite of engine.py does not enforce ON DELETE CASCADE.
_STUDENT_DATA = (Chat, Favorite, Constraints, Audit)


def exists(student_id: uuid.UUID) -> bool:
    with engine.session() as db:
        return db.get(Student, student_id) is not None


def save_audit(student_id: uuid.UUID, audit_json: str) -> None:
    with engine.session() as db:
        db.add(
            Audit(
                student_id=student_id,
                audit_encrypted=crypto.encrypt(audit_json),
                confirmed_at=datetime.now(UTC),
            )
        )
        db.commit()


def latest_audit(student_id: uuid.UUID) -> str | None:
    """The newest audit's JSON, or None when there is none or it cannot be read."""
    with engine.session() as db:
        token = db.scalar(
            select(Audit.audit_encrypted)
            .where(Audit.student_id == student_id)
            .order_by(Audit.id.desc())
            .limit(1)
        )
    if token is None:
        return None
    try:
        return crypto.decrypt(token)
    except crypto.DecryptError:
        log.warning("audit: stored audit cannot be decrypted; ignoring it")
        return None


def add_chat_messages(student_id: uuid.UUID, messages: list[tuple[str, str]]) -> None:
    """Appends (role, message JSON) pairs. role is 'user' or 'assistant'."""
    with engine.session() as db:
        db.add_all(
            Chat(student_id=student_id, role=role, message_encrypted=crypto.encrypt(text))
            for role, text in messages
        )
        db.commit()


def chat_messages(student_id: uuid.UUID) -> list[tuple[str, str]]:
    """Every (role, message JSON) pair in order. Messages this key cannot read are skipped."""
    with engine.session() as db:
        rows = db.execute(
            select(Chat.role, Chat.message_encrypted)
            .where(Chat.student_id == student_id)
            .order_by(Chat.id)
        ).all()
    messages: list[tuple[str, str]] = []
    for role, token in rows:
        try:
            messages.append((role, crypto.decrypt(token)))
        except crypto.DecryptError:
            log.warning("chat: a stored message cannot be decrypted; skipping it")
    return messages


def save_constraints(student_id: uuid.UUID, value: dict[str, Any]) -> None:
    with engine.session() as db:
        row = db.get(Constraints, student_id)
        if row is None:
            db.add(Constraints(student_id=student_id, value=value))
        else:
            row.value = value
            row.updated_at = datetime.now(UTC)
        db.commit()


def load_constraints(student_id: uuid.UUID) -> dict[str, Any] | None:
    with engine.session() as db:
        row = db.get(Constraints, student_id)
        return dict(row.value) if row else None


def save_favorites(student_id: uuid.UUID, professor_ids: set[str]) -> None:
    """Makes the stored favorites exactly `professor_ids`."""
    with engine.session() as db:
        stored = set(
            db.scalars(select(Favorite.professor_id).where(Favorite.student_id == student_id))
        )
        removed = stored - professor_ids
        if removed:
            db.execute(
                delete(Favorite).where(
                    Favorite.student_id == student_id, Favorite.professor_id.in_(removed)
                )
            )
        db.add_all(
            Favorite(student_id=student_id, professor_id=p) for p in professor_ids - stored
        )
        db.commit()


def load_favorites(student_id: uuid.UUID) -> set[str]:
    with engine.session() as db:
        return set(
            db.scalars(select(Favorite.professor_id).where(Favorite.student_id == student_id))
        )


def delete_student(student_id: uuid.UUID) -> bool:
    """Deletes the student's audits, chats, constraints, favorites and row, in one
    transaction. False when there was no such student."""
    with engine.session() as db:
        for model in _STUDENT_DATA:
            db.execute(delete(model).where(model.student_id == student_id))
        student = db.get(Student, student_id)
        if student is not None:
            db.delete(student)
        db.commit()
    return student is not None
