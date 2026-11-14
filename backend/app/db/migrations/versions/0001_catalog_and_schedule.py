"""Catalog and class schedule tables: the same SQL as backend/app/db/schema.sql.

Built from the structure of scripts/out/course_search_clean.json
(scripts/scrape_course_search.py -> scripts/data_cleaner.py), loaded by
scripts/populate_db.py. Column names follow the ENG-01 contracts in
backend/app/contracts/ where a contract field exists.

JSON -> table map:
  top level (source, term, subjects, scraped_at, count) -> scrape_runs
  term / term_code / block                              -> terms
  courses{code: {prereq, requisites}}                   -> courses.prereq, course_requisites
  section title, department, description, course_areas  -> courses (same for every section of a course)
  section credits (max), requisites_expression          -> courses.credits, courses.prereq_text
  sections[]                                            -> sections
  sections[].meetings[] + sections[].locations[]        -> meetings (same position = same meeting)
  sections[].instructors[]                              -> professors, section_instructors
  scripts/out/faculty.json (directory profiles)         -> professors (profile columns), professor_sources

Values scraped from the site (status, class_type, delivery_method, grading...)
are stored as text, exactly as the site prints them, because the site has
values the contracts do not list yet (for example status "reopened").

Every statement is `IF NOT EXISTS`, so a database made with schema.sql is taken
over as it is, data included: `alembic upgrade head` keeps its rows. A change to
schema.sql needs a new migration too.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from alembic import op

revision = "0001"
down_revision: str | None = None
branch_labels = None
depends_on = None

SQL = r"""
-- One row per school. Every catalog, schedule and professor table points here (plan.md).
CREATE TABLE IF NOT EXISTS universities (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    short_code  text NOT NULL UNIQUE,                 -- e.g. 'byui'
    name        text NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);

-- One row per run of the scraper (the top level of the JSON file).
CREATE TABLE IF NOT EXISTS scrape_runs (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    university_id  bigint NOT NULL REFERENCES universities (id),
    source_url     text NOT NULL,                     -- "source"
    term_code      text NOT NULL,                     -- "term", e.g. '2027;WI'
    subjects       text[] NOT NULL DEFAULT '{}',      -- "subjects", e.g. {CSE,CIT,MATH}
    scraped_at     timestamptz NOT NULL,              -- "scraped_at"
    section_count  integer NOT NULL CHECK (section_count >= 0),  -- "count"
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (university_id, source_url, scraped_at)
);

-- Terms and their blocks: '2027;WI' (full semester), '2027;WI;W1' (First Block),
-- '2027;WI;W2' (Second Block). A block points to its full-semester term.
CREATE TABLE IF NOT EXISTS terms (
    id              bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    university_id   bigint NOT NULL REFERENCES universities (id),
    code            text NOT NULL,                    -- "term_code"
    name            text,                             -- e.g. 'Winter 2027'
    block_kind      text NOT NULL CHECK (block_kind IN ('full', 'first', 'second')),
    block_label     text,                             -- "block", e.g. 'Winter First Block'; NULL for full semester
    parent_term_id  bigint REFERENCES terms (id),     -- the full semester, for a block
    start_date      date,
    end_date        date,
    created_at      timestamptz NOT NULL DEFAULT now(),
    UNIQUE (university_id, code),
    CHECK (start_date IS NULL OR end_date IS NULL OR start_date <= end_date),
    CHECK ((block_kind = 'full') = (parent_term_id IS NULL))
);

-- One row per course code. Title, department, description and course areas are
-- the same for every section of a course, so they are stored here once.
CREATE TABLE IF NOT EXISTS courses (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    university_id  bigint NOT NULL REFERENCES universities (id),
    code           text NOT NULL                      -- "course", e.g. 'CSE 111'
                   CHECK (code ~ '^[A-Z]{2,5} \d{3}[A-Z]?$'),
    title          text NOT NULL,                     -- "title"
    department     text NOT NULL,                     -- "department"
    description    text NOT NULL DEFAULT '',          -- "description"
    course_areas   text[] NOT NULL DEFAULT '{}',      -- "course_areas", e.g. {PSEN,ONLN}
    -- PrereqExpression tree (backend/app/contracts/catalog.py).
    -- NULL = not read yet, NOT "no prerequisites".
    -- {"type": "all", "items": []} = the site lists no prerequisites.
    prereq         jsonb CHECK (
                       prereq IS NULL
                       OR (jsonb_typeof(prereq) = 'object'
                           AND prereq ->> 'type' IN ('all', 'any', 'course', 'condition', 'unparsed'))
                   ),
    -- Catalog columns (DATA-04), filled by scripts/populate_db.py from the scrape.
    credits        numeric(4, 2) CHECK (credits >= 0), -- most a section offers (CSE 290R: 1-3 -> 3)
    prereq_text    text,                              -- "requisites_expression", as the site lists it
    catalog_year   text,                              -- e.g. '2026-2027', derived from the term
    source_url     text,
    created_at     timestamptz NOT NULL DEFAULT now(),
    updated_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (university_id, code)
);

-- Columns added by DATA-04, for databases created before it.
ALTER TABLE courses ADD COLUMN IF NOT EXISTS credits     numeric(4, 2) CHECK (credits >= 0);
ALTER TABLE courses ADD COLUMN IF NOT EXISTS prereq_text text;

-- The raw rows of the "Course Requisites" page, in page order: the source the
-- prereq tree was built from. Kept so the tree can be rebuilt or checked.
CREATE TABLE IF NOT EXISTS course_requisites (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    course_id             bigint NOT NULL REFERENCES courses (id) ON DELETE CASCADE,
    position              integer NOT NULL CHECK (position >= 0),  -- order on the page
    connector_before      text,             -- "connector_before": 'OR', 'AND', '-' or NULL
    condition             text,             -- "condition": 'AND' inside a group, or NULL
    group_code            text,             -- "group": rows with the same group are joined by AND
    requisite_type        text NOT NULL,    -- "type": 'Course Prerequisite', 'Course Co-Requisite'...
    text                  text NOT NULL,    -- "text", exactly as the site prints it
    required_course_code  text,             -- "course", NULL for exams and other conditions
    min_grade             text,             -- "min_grade", e.g. 'C-'
    UNIQUE (course_id, position)
);

-- One row per section of a course in a term.
CREATE TABLE IF NOT EXISTS sections (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    university_id         bigint NOT NULL REFERENCES universities (id),
    term_id               bigint NOT NULL REFERENCES terms (id),     -- "term_code" (and "block")
    course_id             bigint NOT NULL REFERENCES courses (id),   -- "course"
    scrape_run_id         bigint REFERENCES scrape_runs (id),
    section               text NOT NULL,                  -- "section", e.g. '01', 'A1'
    credits               numeric(4, 2) NOT NULL CHECK (credits >= 0),
    class_type            text,                           -- "class_type": 'DAY', 'ONLN', 'DIST'
    delivery_method       text,                           -- "delivery_method": 'In-Person', 'Online', ...
    grading               text,                           -- "grading": 'Letter Grade', ...
    remarks               text[] NOT NULL DEFAULT '{}',   -- "remarks"
    note                  text,                           -- "note"
    section_requirements  text[] NOT NULL DEFAULT '{}',   -- "section_requirements"
    status                text,                           -- "status": 'open', 'closed', 'reopened'
    status_raw            text,                           -- "status_raw": 'Closed (0 out of 30 seats)'
    seats_open            integer CHECK (seats_open >= 0),
    seats_total           integer CHECK (seats_total >= 0),
    seats_as_of           timestamptz,                    -- always shown as "seats as of <time>"
    source_url            text NOT NULL,                  -- "source_url"
    source_note           text,                           -- "source_note"
    fetched_at            timestamptz,                    -- "fetched_at"
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now(),
    UNIQUE (term_id, course_id, section)
);

-- One row per meeting line of a section. meetings[i] and locations[i] in the
-- JSON describe the same meeting, so they share a row.
CREATE TABLE IF NOT EXISTS meetings (
    id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    section_id  bigint NOT NULL REFERENCES sections (id) ON DELETE CASCADE,
    position    integer NOT NULL CHECK (position >= 0),
    raw         text,                   -- "raw", e.g. 'TR 12:45-01:45PM'
    days        text NOT NULL DEFAULT ''  -- "days", e.g. 'TR'; '' for online / arranged
                CHECK (days ~ '^[MTWRFSU]*$'),
    time_raw    text,                   -- "time_raw", e.g. '12:45-01:45PM'; NULL when no set time
    start_time  time,                   -- filled by ENG-02's parser from time_raw
    end_time    time,
    start_date  date NOT NULL,          -- "start_date"
    end_date    date NOT NULL,          -- "end_date"
    room        text,                   -- "room", e.g. 'STC 231', 'Online Class'
    location    text,                   -- locations[].location, e.g. 'MAIN Campus, Science & Technology Ctr, 231'
    tba         boolean NOT NULL DEFAULT false,
    UNIQUE (section_id, position),
    CHECK (start_date <= end_date),
    CHECK ((start_time IS NULL) = (end_time IS NULL)),
    CHECK (start_time IS NULL OR start_time < end_time)
);

-- One row per person. Two people with the same name in different departments
-- stay two rows (AGENTS.md: never merge professors on name alone).
CREATE TABLE IF NOT EXISTS professors (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    university_id  bigint NOT NULL REFERENCES universities (id),
    full_name      text NOT NULL,        -- as printed: 'Lawrence, Bradley W.'
    last_name      text,
    first_name     text,
    middle_name    text,
    department     text NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (university_id, full_name, department)
);

-- Public directory profile (DATA-05, scripts/scrape_faculty.py -> scripts/out/faculty.json),
-- matched to the schedule name by backend/app/schools/byui/professor_matching.py.
-- All NULL when no profile was matched with confidence >= 0.8. Added with ALTER so a
-- database made before DATA-05 gets the columns too.
ALTER TABLE professors ADD COLUMN IF NOT EXISTS directory_url    text;
ALTER TABLE professors ADD COLUMN IF NOT EXISTS match_confidence real
    CHECK (match_confidence BETWEEN 0 AND 1);
ALTER TABLE professors ADD COLUMN IF NOT EXISTS job_title        text;   -- 'Faculty', 'Department Chair'
ALTER TABLE professors ADD COLUMN IF NOT EXISTS email            text;   -- public directory email
ALTER TABLE professors ADD COLUMN IF NOT EXISTS office           text;   -- '127 ETC'
ALTER TABLE professors ADD COLUMN IF NOT EXISTS image_url        text;
ALTER TABLE professors ADD COLUMN IF NOT EXISTS bio              text;   -- full profile text
-- True only when the profile says so; NULL means unknown, never guessed.
ALTER TABLE professors ADD COLUMN IF NOT EXISTS lists_undergrad_research boolean;
ALTER TABLE professors ADD COLUMN IF NOT EXISTS profile_fetched_at timestamptz;

-- "instructors": a section can have several (up to 3 in the current data).
CREATE TABLE IF NOT EXISTS section_instructors (
    section_id    bigint NOT NULL REFERENCES sections (id) ON DELETE CASCADE,
    professor_id  bigint NOT NULL REFERENCES professors (id),
    position      integer NOT NULL CHECK (position >= 0),  -- order on the page
    PRIMARY KEY (section_id, professor_id)
);

-- One row per profile section (the contract's ProfessorSourceKind). Every professor
-- with a profile has all five; a section the page does not have is ''.
CREATE TABLE IF NOT EXISTS professor_sources (
    university_id  bigint NOT NULL REFERENCES universities (id),
    professor_id   bigint NOT NULL REFERENCES professors (id) ON DELETE CASCADE,
    kind           text NOT NULL
                   CHECK (kind IN ('education', 'interests', 'work_experience', 'research', 'biography')),
    value          text NOT NULL DEFAULT '',
    source_url     text NOT NULL,
    fetched_at     timestamptz NOT NULL,
    PRIMARY KEY (professor_id, kind)
);

-- Claude results that do not change for the same input (AGENTS.md): topic tags now,
-- prerequisite parses and bio summaries later. key = '<namespace>:<sha256 of input>',
-- so the same input is sent to Claude once. Not part of populate_db.py's refresh:
-- the cache survives reloads. subject says what the result is about (the profile URL
-- for topic tags); the newest row per subject is the current one.
CREATE TABLE IF NOT EXISTS llm_cache (
    key         text PRIMARY KEY,
    namespace   text NOT NULL,                  -- 'topic_tags'
    subject     text,
    model       text NOT NULL,
    value       jsonb NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_llm_cache_subject ON llm_cache (namespace, subject, created_at);

-- Lookups the scheduler and the API need.
CREATE INDEX IF NOT EXISTS idx_courses_department          ON courses (department);
CREATE INDEX IF NOT EXISTS idx_course_requisites_required  ON course_requisites (required_course_code);
CREATE INDEX IF NOT EXISTS idx_sections_course             ON sections (course_id);
CREATE INDEX IF NOT EXISTS idx_sections_term               ON sections (term_id);
CREATE INDEX IF NOT EXISTS idx_meetings_section            ON meetings (section_id);
CREATE INDEX IF NOT EXISTS idx_section_instructors_prof    ON section_instructors (professor_id);
CREATE INDEX IF NOT EXISTS idx_courses_prereq              ON courses USING gin (prereq);
"""

TABLES = [
    "professor_sources",
    "section_instructors",
    "meetings",
    "sections",
    "course_requisites",
    "courses",
    "terms",
    "scrape_runs",
    "professors",
    "llm_cache",
    "universities",
]


def upgrade() -> None:
    # Driver SQL: several statements at once, with no bind-parameter parsing.
    op.get_bind().exec_driver_sql(SQL)


def downgrade() -> None:
    for table in TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")
