#!/usr/bin/env python3
"""Topic tags for professors with a public profile, from Claude Haiku (DATA-05).

Reads the profiles that scripts/populate_db.py loaded (professor_sources), sends
each profile once to Claude Haiku (CLAUDE_MODEL_BULK) and stores 3 to 8 tags in
llm_cache, keyed by a SHA-256 of the input. A second run makes 0 Claude calls.
/api/professors reads the newest tags per profile from llm_cache, so reloading the
professors with populate_db.py keeps the tags.

Only public profile text is sent (sections, no name or contact details). This calls
the Claude API and costs money: run it by hand, never in CI or tests.

Needs DATABASE_URL and ANTHROPIC_API_KEY, and the backend's packages
(pip install -e ".[dev]").

Usage:
    python3 scripts/tag_professors.py --dry-run     # how many calls, no API
    python3 scripts/tag_professors.py               # professors teaching this semester
    python3 scripts/tag_professors.py --all         # every professor with a profile
    python3 scripts/tag_professors.py --limit 5
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "backend"))

import os  # noqa: E402

import psycopg  # noqa: E402
from psycopg.rows import dict_row  # noqa: E402

from app.db.llm_cache import DbTagCache  # noqa: E402
from app.llm import client  # noqa: E402
from app.llm import topic_tags as tt  # noqa: E402

# One row per profile (the same profile can be attached to two schedule rows).
PROFILES = """
SELECT p.directory_url, min(p.full_name) AS name,
       jsonb_object_agg(ps.kind, ps.value) AS sources
FROM professors p
JOIN professor_sources ps ON ps.professor_id = p.id
WHERE p.directory_url IS NOT NULL
  {teaching}
GROUP BY p.directory_url
ORDER BY min(p.full_name)
"""
TEACHING = "AND EXISTS (SELECT 1 FROM section_instructors si WHERE si.professor_id = p.id)"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--all", action="store_true", help="also faculty not teaching this semester")
    ap.add_argument("--limit", type=int)
    ap.add_argument("--dry-run", action="store_true", help="count calls, do not call Claude")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        print("DATABASE_URL is not set.", file=sys.stderr)
        return 1
    with psycopg.connect(url, row_factory=dict_row, connect_timeout=10) as conn:
        rows = conn.execute(PROFILES.format(teaching="" if args.all else TEACHING)).fetchall()
    profiles = [(r["directory_url"], r["name"], dict(r["sources"])) for r in rows][: args.limit]

    cache = DbTagCache()
    if args.dry_run:
        todo = Counter(
            "skipped"
            if len(tt.profile_input(s).split()) < tt.MIN_WORDS
            else ("cached" if cache.get(tt.cache_key(tt.profile_input(s))) is not None else "call")
            for _, _, s in profiles
        )
        print(
            f"{len(profiles)} profiles: {todo['call']} Claude calls needed, "
            f"{todo['cached']} cached, {todo['skipped']} too little text ({client.bulk_model()})"
        )
        return 0
    if not client.is_configured():
        print("ANTHROPIC_API_KEY is not set.", file=sys.stderr)
        return 1

    counts: Counter[str] = Counter()
    for i, (url, name, sources) in enumerate(profiles, 1):
        result = tt.tag_profile(sources, subject=url, cache=cache)
        counts[result.status] += 1
        if result.status in ("tagged", "failed", "error"):
            print(f"  {i}/{len(profiles)} {name}: {result.status} {', '.join(result.tags)}")
    print(
        f"{len(profiles)} profiles: {counts['tagged']} tagged (Claude calls), "
        f"{counts['cached']} cached (0 calls), {counts['skipped']} too little text, "
        f"{counts['failed']} failed validation twice, {counts['error']} API errors"
    )
    return 1 if counts["error"] else 0


if __name__ == "__main__":
    sys.exit(main())
