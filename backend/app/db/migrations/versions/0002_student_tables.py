"""Student-side tables: students, audits, constraints, favorites, chats.

No table has a column for a name, email, password or BYU-Idaho ID number
(AGENTS.md, "Student privacy"). Audit JSON and chat messages are stored
encrypted with DATA_KEY (bytea; the encryption itself is DATA-06). Deleting a
student deletes their audits, constraints, favorites and chats (`DELETE /api/me`).

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from alembic import op

revision = "0002"
down_revision: str | None = "0001"
branch_labels = None
depends_on = None

SQL = """
-- One row per anonymous session (the signed `sid` cookie). app/db/models.py: Student.
CREATE TABLE students (
    id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at    timestamptz NOT NULL DEFAULT now(),
    last_seen_at  timestamptz NOT NULL DEFAULT now(),
    consented_at  timestamptz,
    -- NULL = unknown: the app asks the student. Values of the contract's Track.
    track         text CHECK (track IN ('fall_winter', 'winter_spring', 'spring_fall', 'online')),
    catalog_year  text
);

-- The confirmed DegreeAudit, as JSON encrypted with DATA_KEY. Never the PDF.
CREATE TABLE audits (
    id               bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    student_id       uuid NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    audit_encrypted  bytea NOT NULL,
    confirmed_at     timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_audits_student ON audits (student_id, created_at);

-- The ConstraintSet behind the chips (GET / PUT /api/constraints). One per student.
CREATE TABLE constraints (
    student_id  uuid PRIMARY KEY REFERENCES students (id) ON DELETE CASCADE,
    value       jsonb NOT NULL,
    updated_at  timestamptz NOT NULL DEFAULT now()
);

-- Favorite professors. professor_id is the API's professor id, not a foreign key:
-- scripts/populate_db.py reloads the professors table, and a foreign key would block it.
CREATE TABLE favorites (
    student_id    uuid NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    professor_id  text NOT NULL,
    created_at    timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (student_id, professor_id)
);

-- Chat messages, encrypted with DATA_KEY.
CREATE TABLE chats (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    student_id         uuid NOT NULL REFERENCES students (id) ON DELETE CASCADE,
    role               text NOT NULL CHECK (role IN ('user', 'assistant')),
    message_encrypted  bytea NOT NULL,
    created_at         timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX idx_chats_student ON chats (student_id, created_at);
"""

TABLES = ["chats", "favorites", "constraints", "audits", "students"]


def upgrade() -> None:
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE {table}")
