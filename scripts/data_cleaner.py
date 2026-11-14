#!/usr/bin/env python3
"""Turn the scraped requisite rows into the PrereqExpression tree from ENG-01.

Reads the JSON written by scrape_course_search.py and writes a copy that is
identical to it, field for field, except that every section gains two fields:

- `prereq`: the section's course prerequisites as a tree in the shape of
  `backend/app/contracts/catalog.py` (all / any / course / condition / unparsed),
  built from the section's `requisites` rows.
- `section_requirements`: the "Section Requirement" rows (permission, credit
  hours, online-only...). They are rules about the section, not course
  prerequisites, so they are kept out of the tree.

No network calls. Standard library only.

How the rows become a tree:
- Rows with the same group number are joined by AND -> {"type": "all"}.
- Groups are joined by the connector before them. OR binds groups together
  -> {"type": "any"}; AND splits the top level -> {"type": "all"} of those.
- Co-requisites and concurrent requisites become courses with concurrent_ok=true.
- Exams (LUC, ACT, SAT, ALEKS, Math Path) become conditions such as
  "LUC exam: SCORE >= 110" until the contract has an exam type.
- Wildcard codes ("MATH 221*" = any MATH 221 version, "MATH 11***" = any MATH
  11x course) become "any" of the matching courses in the data, plus a condition
  "Any other ... course" so a student with a match we do not know gets a
  warning instead of a wrong "not met".
- Anything unexpected becomes {"type": "unparsed"}: shown as a warning, never
  treated as "no prerequisites".
- A section with no requisite rows gets {"type": "all", "items": []}, which
  means "the site lists none". `prereq: null` means it could not be read.

Usage:
    python3 scripts/data_cleaner.py
    python3 scripts/data_cleaner.py --in scripts/out/course_search.json \
        --out scripts/out/course_search_clean.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent / "out"

# Same pattern as CourseCode in backend/app/contracts/catalog.py.
COURSE_CODE = re.compile(r"^[A-Z]{2,5} \d{3}[A-Z]?$")

PREREQ_TYPES = {
    "Course Prerequisite": False,  # value: concurrent_ok
    "Course Co-Requisite": True,
    "Concurrent Requisite": True,
}
SECTION_TYPE = "Section Requirement"

EXAM_NAMES = [  # longest names first, so "SAT (2016+)" wins over "SAT"
    ("Literacy and Understanding Computing", "LUC"),
    ("American College Test", "ACT"),
    ("Scholastic Aptitude Test (2016+)", "SAT (2016+)"),
    ("Scholastic Aptitude Test", "SAT"),
    ("ALEKS Math Placement", "ALEKS"),
    ("The Math Path", "Math Path"),
]
EXAM = re.compile(r"^(.*?) exam must be taken with a (\w+) score of (\d+) or greater", re.I)
WILDCARD = re.compile(r"^([A-Z]{2,5}) (\d+)\*+$")  # MATH 11***, MATH 221*
COURSE_TEXT = re.compile(
    r"Course\s+([A-Z]+)\s+(\S+)\s+must be taken(?:\s+with a grade of\s+(\S+)\s+or better)?", re.I
)


def course_node(code: str, grade: str | None, concurrent_ok: bool) -> dict:
    return {
        "type": "course",
        "course_code": code,
        "min_grade": grade,
        "concurrent_ok": concurrent_ok,
    }


def expand_wildcard(
    code: str, grade: str | None, concurrent_ok: bool, known: set[str]
) -> dict | None:
    """ "MATH 221*" -> any of the known MATH 221x courses, plus a condition for the others.

    The site uses * for "any characters": MATH 11*** is any MATH 11x course,
    MATH 221* is any version of MATH 221. Only courses that exist in our data are
    listed; a student who took another matching course gets a warning, not a "not met".
    """
    m = WILDCARD.match(code)
    if not m:
        return None
    prefix = f"{m.group(1)} {m.group(2)}"
    matches = sorted(c for c in known if c.startswith(prefix) and COURSE_CODE.match(c))
    label = f"{prefix}x" if len(m.group(2)) < 3 else prefix  # "MATH 11x", "MATH 221"
    other = "other " if matches else ""
    note = f"Any {other}{label} course ({code})" + (f", {grade} or better" if grade else "")
    items = [course_node(c, grade, concurrent_ok) for c in matches] + [
        {"type": "condition", "text": note}
    ]
    return combine("any", items)


def leaf(row: dict, known: set[str]) -> dict:
    """One requisite row -> course, condition or unparsed node."""
    text = row["text"]
    exam = EXAM.match(text)
    if exam:
        name = next(
            (short for full, short in EXAM_NAMES if exam.group(1).startswith(full)), exam.group(1)
        )
        return {
            "type": "condition",
            "text": f"{name} exam: {exam.group(2).upper()} >= {exam.group(3)}",
        }

    code, grade = row.get("course"), row.get("min_grade")
    if not code:
        m = COURSE_TEXT.search(text)
        if m:
            code, grade = f"{m.group(1).upper()} {m.group(2).upper()}", m.group(3)
    concurrent_ok = PREREQ_TYPES.get(row["type"], False)
    if code and COURSE_CODE.match(code):
        return course_node(code, grade, concurrent_ok)
    if code:
        expanded = expand_wildcard(code, grade, concurrent_ok, known)
        if expanded:
            return expanded
        return {"type": "unparsed", "text": text}  # a course code we do not understand
    return {"type": "condition", "text": text}


def combine(kind: str, items: list[dict]) -> dict:
    """all/any node: merges nested nodes of the same kind, drops exact duplicates,
    and returns a single item on its own."""
    unique: list[dict] = []
    for item in items:
        for sub in item["items"] if item["type"] == kind and item["items"] else [item]:
            if sub not in unique:
                unique.append(sub)
    return unique[0] if len(unique) == 1 else {"type": kind, "items": unique}


def build_prereq(rows: list[dict], known: set[str]) -> dict:
    rows = [r for r in rows if r["type"] != SECTION_TYPE]
    if not rows:
        return {"type": "all", "items": []}  # the site lists no prerequisites

    unknown = {r["type"] for r in rows} - PREREQ_TYPES.keys()
    inner = {r["condition"] for r in rows} - {None, "AND"}
    if unknown or inner:
        # A row type or in-group connector we have not seen: keep it all as a warning.
        return {"type": "unparsed", "text": " | ".join(r["text"] for r in rows)}

    # Consecutive rows with the same group number form one AND group.
    groups: list[tuple[str, list[dict]]] = []  # (connector before the group, rows)
    for r in rows:
        if groups and r["group"] == groups[-1][1][-1]["group"]:
            groups[-1][1].append(r)
        else:
            groups.append(((r["connector_before"] or "AND").upper(), [r]))

    # OR joins neighbouring groups; AND (or "-") starts a new top-level part.
    parts: list[list[dict]] = []
    for i, (connector, group_rows) in enumerate(groups):
        node = combine("all", [leaf(r, known) for r in group_rows])
        if i > 0 and connector == "OR":
            parts[-1].append(node)
        else:
            parts.append([node])
    return combine("all", [combine("any", p) for p in parts])


def section_requirements(rows: list[dict]) -> list[str]:
    return [r["text"] for r in rows if r["type"] == SECTION_TYPE]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--in", dest="src", default=str(OUT_DIR / "course_search.json"))
    ap.add_argument("--out", default=str(OUT_DIR / "course_search_clean.json"))
    args = ap.parse_args()

    data = json.loads(Path(args.src).read_text(encoding="utf-8"))
    if "courses" in data:
        raise SystemExit(
            f"{args.src} is already a cleaned file. Run this on the scraper's course_search.json."
        )
    # Real course codes in the data (offered sections + courses named in requisites),
    # used to expand wildcards such as MATH 221*.
    known = {s["course"] for s in data["sections"]}
    known |= {
        r["course"] for s in data["sections"] for r in s.get("requisites") or [] if r.get("course")
    }
    # Every original field stays as it is; each section only gains `prereq` and
    # `section_requirements`, placed right after its `requisites`.
    counts = {
        "tree": 0,
        "none_listed": 0,
        "unreadable": 0,
        "with_unparsed": 0,
        "with_section_reqs": 0,
    }
    sections = []
    for s in data["sections"]:
        rows = s.get("requisites")
        if rows is None:  # the requisites page could not be read
            prereq, reqs = None, []
            counts["unreadable"] += 1
        else:
            prereq, reqs = build_prereq(rows, known), section_requirements(rows)
            counts["none_listed" if prereq == {"type": "all", "items": []} else "tree"] += 1
        if '"unparsed"' in json.dumps(prereq):
            counts["with_unparsed"] += 1
        if reqs:
            counts["with_section_reqs"] += 1
        cleaned = {}
        for key, value in s.items():
            cleaned[key] = value
            if key == "requisites_expression":
                cleaned["prereq"] = prereq
                cleaned["section_requirements"] = reqs
        cleaned.setdefault("prereq", prereq)
        cleaned.setdefault("section_requirements", reqs)
        sections.append(cleaned)
    data["sections"] = sections

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(
        f"{len(sections)} sections: {counts['tree']} with prerequisites, "
        f"{counts['none_listed']} with none listed, "
        f"{counts['unreadable']} unreadable, {counts['with_unparsed']} with an unparsed part, "
        f"{counts['with_section_reqs']} with section requirements. Wrote {out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
