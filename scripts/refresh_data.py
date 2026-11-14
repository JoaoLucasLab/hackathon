#!/usr/bin/env python3
"""Refresh the database from the public Course Search: scrape, clean, load.

The one script to schedule. It runs, in order:

1. scrape_course_search.py  downloads the class schedule (the major subjects:
                            a few hours; --subjects DEMO: about 25 minutes)
2. data_cleaner.py          adds prerequisite trees and class times
3. populate_db.py           loads the class schedule and the course catalog

It writes new files next to the old ones first (course_search.new.json,
course_search_clean.new.json) and replaces the old files only after the database
load succeeds. If any step fails, it stops: the database and the old files stay
as they were.

Before loading, it refuses a scrape that looks incomplete: the scraper stopped or
a subject failed (exit code 1), a subject has no sections that the scraper did
not report as empty, or the file has far
fewer sections than the last good one (--min-ratio, 0.8 by default). A real drop
in sections can be loaded with --force.

Only one copy runs at a time (a lock file in scripts/out/). This runs a live
scraper against BYU-Idaho: run it only when the data needs refreshing (at most
once a day), never in CI or tests, and keep the scraper's delays (AGENTS.md).

Usage:
    python3 scripts/refresh_data.py
    python3 scripts/refresh_data.py --skip-scrape          # clean and load the last scrape again
    python3 scripts/refresh_data.py --subjects DEMO        # only CSE, CIT and MATH
    python3 scripts/refresh_data.py --subjects ALL         # every subject (many hours)
    python3 scripts/refresh_data.py --container course-planner-db --user app --database app

Schedule (cron, every day at 03:00; use the full path to the Python that has the
backend's packages):
    0 3 * * * cd /path/to/repo && /path/to/python scripts/refresh_data.py \
        >> scripts/out/refresh.log 2>&1
(cron needs that on one line; it is split here only to fit.)
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
OUT_DIR = SCRIPTS / "out"
RAW = OUT_DIR / "course_search.json"
CLEAN = OUT_DIR / "course_search_clean.json"
RAW_NEW = OUT_DIR / "course_search.new.json"
CLEAN_NEW = OUT_DIR / "course_search_clean.new.json"
LOCK = OUT_DIR / ".refresh.lock"


def log(message: str) -> None:
    print(f"[{datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def run(step: str, *args: str) -> bool:
    log(f"{step}: started")
    result = subprocess.run([sys.executable, *args])
    log(f"{step}: {'done' if result.returncode == 0 else f'FAILED (exit {result.returncode})'}")
    return result.returncode == 0


def scrape_problems(new: Path, last: Path, min_ratio: float) -> list[str]:
    """Reasons not to load the new scrape. Empty when it looks complete."""
    data = json.loads(new.read_text(encoding="utf-8"))
    sections = data["sections"]
    problems = []
    # Older files have no sections_by_subject; their codes match the course prefix.
    counts = data.get("sections_by_subject") or {
        s: sum(x["course"].split()[0] == s for x in sections) for s in data["subjects"]
    }
    empty = set(data.get("empty_subjects", []))
    for subject in data["subjects"]:
        if not counts.get(subject) and subject not in empty:
            problems.append(f"subject {subject} has no sections")
    if last.exists():
        before = len(json.loads(last.read_text(encoding="utf-8"))["sections"])
        if len(sections) < before * min_ratio:
            problems.append(
                f"{len(sections)} sections, fewer than {min_ratio:.0%} of the last good "
                f"scrape ({before}); use --force if the drop is real"
            )
    return problems


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--skip-scrape", action="store_true", help="reuse the last scrape")
    ap.add_argument("--force", action="store_true", help="load even if sections dropped")
    ap.add_argument("--min-ratio", type=float, default=0.8)
    ap.add_argument("--subjects", nargs="+", help="passed to the scraper (ALL, DEMO or codes)")
    ap.add_argument("--container", default="my-postgres-myplan")
    ap.add_argument("--user", default="app_user")
    ap.add_argument("--database", default="app_db")
    args = ap.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    with open(LOCK, "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            log("another refresh is running; stopping")
            return 1

        if args.skip_scrape:
            raw = RAW
        else:
            raw = RAW_NEW
            scraper = [str(SCRIPTS / "scrape_course_search.py")]
            if args.subjects:  # otherwise the scraper's default, MAJOR_SUBJECTS
                scraper += ["--subjects", *args.subjects]
            if not run("scrape", *scraper, "--out", str(raw)):
                log("the scrape is incomplete; the database was not touched")
                return 1
            problems = scrape_problems(raw, RAW, args.min_ratio)
            if problems and not args.force:
                log("the scrape looks incomplete; the database was not touched:")
                for problem in problems:
                    log(f"  {problem}")
                return 1

        steps = [
            ("clean", str(SCRIPTS / "data_cleaner.py"), "--in", str(raw), "--out", str(CLEAN_NEW)),
            (
                "load",
                str(SCRIPTS / "populate_db.py"),
                "--in",
                str(CLEAN_NEW),
                "--container",
                args.container,
                "--user",
                args.user,
                "--database",
                args.database,
            ),
        ]
        for step, *step_args in steps:
            if not run(step, *step_args):
                log("stopped; the database and the last good files were not changed")
                return 1

        # The database has the new data: the new files become the last good ones.
        if raw == RAW_NEW:
            os.replace(RAW_NEW, RAW)
        os.replace(CLEAN_NEW, CLEAN)
        log("refresh complete")
        return 0


if __name__ == "__main__":
    sys.exit(main())
