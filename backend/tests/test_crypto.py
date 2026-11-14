"""DATA-06: audit JSON and chat messages are encrypted at rest with DATA_KEY, and no
table can hold a student's name or ID number.

Runs on the in-memory database (no DATABASE_URL in tests). The raw columns are read
with plain SQL, as by someone holding a copy of the database.
"""

from __future__ import annotations

import json

import pytest
from tests.student_helpers import REPLY, raw_column, script_chat, session_client

from app.api import audit_store
from app.config import FIXTURES_DIR, REPO_ROOT
from app.contracts import DegreeAudit
from app.db import crypto, student_store
from app.db.models import Base

FAKE_IDS = ("123-45-6789", "987654321")
FORBIDDEN_COLUMNS = ("name", "email", "password", "byui_id", "student_number", "inumber", "ssn")


def test_round_trip() -> None:
    token = crypto.encrypt('{"course": "CSE 111"}')
    assert b"CSE" not in token
    assert crypto.decrypt(token) == '{"course": "CSE 111"}'


def test_another_key_cannot_read_it() -> None:
    token = crypto.fernet_for("some other key").encrypt(b"CSE 111")
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt(token)


def test_the_key_comes_from_data_key() -> None:
    a, b = crypto.fernet_for("one secret"), crypto.fernet_for("one secret")
    assert b.decrypt(a.encrypt(b"x")) == b"x"


def test_stored_audit_has_no_course_code_in_plain_text() -> None:
    client, student_id = session_client()
    audit = json.loads((FIXTURES_DIR / "audit.json").read_text())
    codes = {c["course_code"] for c in audit["courses"]}
    assert len(codes) > 3
    assert client.put("/api/audit", json=audit).status_code == 200
    rows = raw_column("audits", "audit_encrypted", student_id)
    assert len(rows) == 1
    # Codes have a space ("CSE 110"); the encrypted bytes are base64, which never has one.
    assert not any(code.encode() in rows[0] for code in codes)
    assert b"Computer Science" not in rows[0]
    assert "CSE 110" in crypto.decrypt(rows[0])


def test_stored_chat_has_no_course_code_in_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    script_chat(monkeypatch)
    client, student_id = session_client()
    res = client.post("/api/chat", json={"message": "Can I take CSE 210?"})
    assert res.status_code == 200
    rows = raw_column("chats", "message_encrypted", student_id)
    assert len(rows) == 2
    assert not any(b"CSE 210" in r for r in rows)
    assert "Can I take CSE 210?" in crypto.decrypt(rows[0])
    assert REPLY in crypto.decrypt(rows[1])


def test_audit_with_a_fake_id_number_is_saved_without_it() -> None:
    raw = (FIXTURES_DIR / "audits/fake-id-number.json").read_text()
    assert all(fake in raw for fake in FAKE_IDS)
    client, student_id = session_client()
    res = client.put("/api/audit", json=json.loads(raw))
    assert res.status_code == 200
    assert not any(fake in res.text for fake in FAKE_IDS)
    stored = student_store.latest_audit(student_id)
    assert stored is not None
    assert not any(fake in stored for fake in FAKE_IDS)
    assert audit_store.REMOVED in stored
    DegreeAudit.model_validate_json(stored)


def test_no_table_has_a_name_or_id_column() -> None:
    def check(table: str, column: str) -> None:
        assert not any(word in column for word in FORBIDDEN_COLUMNS), f"{table}.{column}"

    for model_table in Base.metadata.tables.values():
        for column in model_table.columns:
            check(model_table.name, column.name)
    # The migration that creates the student tables in Postgres.
    migration = REPO_ROOT / "backend/app/db/migrations/versions/0002_student_tables.py"
    sql = migration.read_text().split('SQL = """', 1)[1].split('"""', 1)[0]
    table = ""
    for line in sql.splitlines():
        if line.startswith("CREATE TABLE"):
            table = line.split()[2]
        elif line.startswith("    ") and not line.strip().startswith("--"):
            check(table, line.split()[0])
    assert table == "chats"
