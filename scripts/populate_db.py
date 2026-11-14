#!/usr/bin/env python3
"""Load the cleaned course data into the local Postgres database.

Reads scripts/out/course_search_clean.json (written by data_cleaner.py) and
fills the tables from backend/app/db/schema.sql. Run the schema first.

Full refresh: every run deletes all rows in the catalog tables and loads the
file again, so the database always matches the latest scrape. Delete and load
happen in one transaction: if anything fails, nothing changes and the old data
stays.

Standard library only: the script builds the SQL and pipes it into psql inside
the Docker container (`docker exec -i ... psql`), so nothing extra needs to be
installed.

Usage:
    python3 scripts/populate_db.py
    python3 scripts/populate_db.py --database app_db --container my-postgres-myplan
    python3 scripts/populate_db.py --sql-out /tmp/populate.sql   # only write the SQL, do not run it
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "out"

UNIVERSITY = ("byui", "Brigham Young University-Idaho")
SEASONS = {"WI": "Winter", "SP": "Spring", "FA": "Fall"}
BLOCK_KINDS = {"W1": "first", "W2": "second", "S1": "first", "S2": "second", "F1": "first", "F2": "second"}

# Same pattern as the CHECK on courses.code and CourseCode in the contracts.
COURSE_CODE = re.compile(r"^[A-Z]{2,5} \d{3}[A-Z]?$")

SECTION_TYPE = "Section Requirement"  # requisite rows about the section, not the course

# Every table this script owns. All of them are emptied and reloaded on each run.
TABLES = [
    "universities", "scrape_runs", "terms", "courses", "course_requisites",
    "sections", "meetings", "professors", "section_instructors",
]


# ------------------------------------------------------------------- SQL literals


def lit(value: object) -> str:
    """Python value -> SQL literal. Strings are single-quoted with quotes doubled
    (standard_conforming_strings is on by default, so backslashes are literal)."""
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def text_array(values: list[str]) -> str:
    return "ARRAY[" + ", ".join(lit(v) for v in values) + "]::text[]" if values else "'{}'::text[]"


def jsonb(value: object) -> str:
    return "NULL" if value is None else lit(json.dumps(value, ensure_ascii=False)) + "::jsonb"


# Subqueries that look rows up by their natural key, so no ids are hard-coded.
UNI = f"(SELECT id FROM universities WHERE short_code = {lit(UNIVERSITY[0])})"


def term_id(code: str) -> str:
    return f"(SELECT id FROM terms WHERE university_id = {UNI} AND code = {lit(code)})"


def course_id(code: str) -> str:
    return f"(SELECT id FROM courses WHERE university_id = {UNI} AND code = {lit(code)})"


def section_id(term_code: str, course: str, section: str) -> str:
    return (
        f"(SELECT id FROM sections WHERE term_id = {term_id(term_code)} "
        f"AND course_id = {course_id(course)} AND section = {lit(section)})"
    )


# --------------------------------------------------------------------- statements


def term_rows(term_codes: set[str], block_labels: dict[str, str]) -> list[str]:
    """Full-semester terms first, then their blocks (which point to them)."""
    sql = []
    full = sorted(c for c in term_codes if c.count(";") == 1)
    blocks = sorted(c for c in term_codes if c.count(";") == 2)
    for code in full + blocks:
        year, season, *block = code.split(";")
        name = f"{SEASONS.get(season, season)} {year}"
        kind = BLOCK_KINDS.get(block[0], "full") if block else "full"
        parent = term_id(f"{year};{season}") if block else "NULL"
        sql.append(
            "INSERT INTO terms (university_id, code, name, block_kind, block_label, parent_term_id) "
            f"VALUES ({UNI}, {lit(code)}, {lit(name)}, {lit(kind)}, {lit(block_labels.get(code))}, {parent});"
        )
    return sql


def course_rows(code: str, s: dict) -> list[str]:
    """One course from its first section: title, department, description, areas and
    prerequisites are the same for every section of a course."""
    sql = [
        "INSERT INTO courses (university_id, code, title, department, description, course_areas, prereq, source_url) "
        f"VALUES ({UNI}, {lit(code)}, {lit(s['title'])}, {lit(s['department'])}, {lit(s['description'] or '')}, "
        f"{text_array(s['course_areas'])}, {jsonb(s['prereq'])}, {lit(s['source_url'])});"
    ]
    # Section Requirement rows belong to the section (sections.section_requirements), not the course.
    course_requisites = [r for r in s.get("requisites") or [] if r["type"] != SECTION_TYPE]
    for pos, r in enumerate(course_requisites):
        sql.append(
            "INSERT INTO course_requisites (course_id, position, connector_before, condition, group_code, "
            "requisite_type, text, required_course_code, min_grade) "
            f"VALUES ({course_id(code)}, {pos}, {lit(r['connector_before'])}, {lit(r['condition'])}, "
            f"{lit(r['group'])}, {lit(r['type'])}, {lit(r['text'])}, {lit(r['course'])}, {lit(r['min_grade'])});"
        )
    return sql


def split_name(full_name: str) -> tuple[str, str | None, str | None]:
    """'Ballou, Kristin Jean' -> ('Ballou', 'Kristin', 'Jean'). full_name keeps the original."""
    last, _, rest = full_name.partition(",")
    parts = rest.split()
    return last.strip(), (parts[0] if parts else None), (" ".join(parts[1:]) or None)


def section_rows(s: dict, run: str) -> list[str]:
    sid = section_id(s["term_code"], s["course"], s["section"])
    sql = [
        "INSERT INTO sections (university_id, term_id, course_id, scrape_run_id, section, credits, class_type, "
        "delivery_method, grading, remarks, note, section_requirements, status, status_raw, seats_open, "
        "seats_total, seats_as_of, source_url, source_note, fetched_at) "
        f"VALUES ({UNI}, {term_id(s['term_code'])}, {course_id(s['course'])}, {run}, {lit(s['section'])}, "
        f"{lit(s['credits'])}, {lit(s['class_type'])}, {lit(s['delivery_method'])}, {lit(s['grading'])}, "
        f"{text_array(s['remarks'])}, {lit(s['note'])}, {text_array(s['section_requirements'])}, "
        f"{lit(s['status'])}, {lit(s['status_raw'])}, {lit(s['seats_open'])}, {lit(s['seats_total'])}, "
        f"{lit(s['seats_as_of'])}, {lit(s['source_url'])}, {lit(s['source_note'])}, {lit(s['fetched_at'])});"
    ]
    # meetings[i] and locations[i] describe the same meeting.
    for pos, m in enumerate(s["meetings"]):
        location = s["locations"][pos]["location"] if pos < len(s["locations"]) else None
        sql.append(
            "INSERT INTO meetings (section_id, position, raw, days, time_raw, start_date, end_date, room, location) "
            f"VALUES ({sid}, {pos}, {lit(m['raw'])}, {lit(m['days'] or '')}, {lit(m['time_raw'])}, "
            f"{lit(m['start_date'])}, {lit(m['end_date'])}, {lit(m['room'])}, {lit(location)});"
        )
    for pos, name in enumerate(s["instructors"]):
        last, first, middle = split_name(name)
        prof = (
            f"(SELECT id FROM professors WHERE university_id = {UNI} AND full_name = {lit(name)} "
            f"AND department = {lit(s['department'])})"
        )
        sql += [
            # One row per name and department: a professor teaching several sections is
            # inserted once, and the same name in another department stays a different
            # professor (AGENTS.md).
            "INSERT INTO professors (university_id, full_name, last_name, first_name, middle_name, department) "
            f"VALUES ({UNI}, {lit(name)}, {lit(last)}, {lit(first)}, {lit(middle)}, {lit(s['department'])}) "
            "ON CONFLICT (university_id, full_name, department) DO NOTHING;",
            f"INSERT INTO section_instructors (section_id, professor_id, position) VALUES ({sid}, {prof}, {pos});",
        ]
    return sql


def build_sql(data: dict) -> str:
    sections = data["sections"]
    run = (
        f"(SELECT id FROM scrape_runs WHERE university_id = {UNI} AND source_url = {lit(data['source'])} "
        f"AND scraped_at = {lit(data['scraped_at'])})"
    )
    block_labels = {s["term_code"]: s["block"] for s in sections if s["block"]}
    first_section = {}
    for s in sections:
        first_section.setdefault(s["course"], s)

    sql = [
        "BEGIN;",
        # Start from empty tables. No CASCADE on purpose: if another table (for example
        # a student's favorites) ever points at these rows, the refresh stops with an
        # error instead of silently deleting that data too.
        f"TRUNCATE {', '.join(TABLES)} RESTART IDENTITY;",
        f"INSERT INTO universities (short_code, name) VALUES ({lit(UNIVERSITY[0])}, {lit(UNIVERSITY[1])});",
        "INSERT INTO scrape_runs (university_id, source_url, term_code, subjects, scraped_at, section_count) "
        f"VALUES ({UNI}, {lit(data['source'])}, {lit(data['term'])}, {text_array(data['subjects'])}, "
        f"{lit(data['scraped_at'])}, {lit(data['count'])});",
    ]
    sql += term_rows({data["term"]} | {s["term_code"] for s in sections}, block_labels)
    for code, s in first_section.items():
        sql += course_rows(code, s)
    for s in sections:
        sql += section_rows(s, run)
    sql.append("COMMIT;")
    return "\n".join(sql) + "\n"


# -------------------------------------------------------------------------- checks


def check(data: dict) -> list[str]:
    """Problems that would make the database reject the load, found before sending anything."""
    problems = []
    for code in sorted({s["course"] for s in data["sections"]}):
        if not COURSE_CODE.match(code):
            problems.append(f"course code {code!r} does not match 'ABC 123' / 'ABC 123X'")
    for s in data["sections"]:
        key = f"{s['course']}-{s['section']}"
        if "prereq" not in s:
            problems.append(f"{key}: no 'prereq' field (load the file from data_cleaner.py, not the scraper's)")
        for m in s["meetings"]:
            if not m["start_date"] or not m["end_date"]:
                problems.append(f"{key}: a meeting has no dates")
    return problems


# --------------------------------------------------------------------------- psql


def psql(args: argparse.Namespace, sql: str) -> str:
    cmd = ["docker", "exec", "-i", args.container, "psql", "-U", args.user, "-d", args.database,
           "-v", "ON_ERROR_STOP=1", "-X", "-A", "-t", "-q"]
    result = subprocess.run(cmd, input=sql, text=True, capture_output=True)
    if result.returncode != 0:
        raise SystemExit(
            f"psql failed. Nothing changed: the old data is still there (the refresh runs in one transaction).\n"
            f"{result.stderr.strip()}"
        )
    return result.stdout


def counts(args: argparse.Namespace) -> dict[str, int]:
    query = " UNION ALL ".join(f"SELECT '{t}', count(*) FROM {t}" for t in TABLES) + ";"
    out = psql(args, query)
    return {name: int(n) for name, n in (line.split("|") for line in out.strip().splitlines())}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--in", dest="src", default=str(OUT_DIR / "course_search_clean.json"))
    ap.add_argument("--container", default="my-postgres-myplan")
    ap.add_argument("--user", default="app_user")
    ap.add_argument("--database", default="app_db")
    ap.add_argument("--sql-out", help="write the SQL to this file instead of running it")
    args = ap.parse_args()

    data = json.loads(Path(args.src).read_text(encoding="utf-8"))
    problems = check(data)
    if problems:
        print("Not loading, the file has problems (the database was not touched):", *problems, sep="\n  ",
              file=sys.stderr)
        return 1
    sql = build_sql(data)

    if args.sql_out:
        Path(args.sql_out).write_text(sql, encoding="utf-8")
        courses = len({s["course"] for s in data["sections"]})
        print(f"Wrote {args.sql_out} ({courses} courses, {len(data['sections'])} sections)")
        return 0

    before = counts(args)
    psql(args, sql)
    after = counts(args)
    print(f"Replaced all data in {args.database} with {args.src}:")
    for table in TABLES:
        print(f"  {table:<20} {before[table]:>5} -> {after[table]:>5} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
