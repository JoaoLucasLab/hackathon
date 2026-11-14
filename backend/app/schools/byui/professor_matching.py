"""Match class-schedule instructors to public directory profiles (DATA-05).

Pure functions: no database and no network. ``scripts/populate_db.py`` calls them
with the class schedule (``scripts/out/course_search_clean.json``) and the
directory scrape (``scripts/out/faculty.json``, from ``scripts/scrape_faculty.py``).

The two sources print names differently and share no key:

- schedule: ``Lawrence, Bradley W.`` in ``Computer Science & Engineering``
- directory: ``Brad Lawrence`` with department ``computer-science-engineering``

Matching rules:

- The last names must be equal (accents, case and dots ignored).
- Same first name: 1.0. A nickname (Brad / Bradley, Bill / William) or the
  directory's first name equal to the schedule's middle name (Nate / Kenneth
  Nathan): 0.9.
- The department does not fit: times 0.7, so the match falls below 0.8.
- Below ``MIN_CONFIDENCE`` the profile is not attached, and the pair is listed in
  the run summary. Two directory people with the same best score: no match.
- ``fixtures/professor_overrides.json`` fixes a match by hand (confidence 1.0) or
  forbids one (``directory_url: null``).

The code never merges two schedule rows: the same name in two departments stays two
rows (AGENTS.md). Both rows may get the same profile.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

MIN_CONFIDENCE = 0.8
NICKNAME_SCORE = 0.9
OTHER_DEPARTMENT_FACTOR = 0.7

# The contract's ProfessorSourceKind values, in display order.
SOURCE_KINDS = ("education", "interests", "work_experience", "research", "biography")

# Directory section headings vary a lot ("Education:", "Previous Work Experience",
# "Bio"...). First pattern that matches wins; unknown headings are ignored.
_HEADING_KINDS = [
    ("education", re.compile(r"educat|degree", re.I)),
    ("research", re.compile(r"research|publication|current project", re.I)),
    ("work_experience", re.compile(r"experience|employment|career|work", re.I)),
    ("interests", re.compile(r"interest|hobb", re.I)),
    ("biography", re.compile(r"^(description|bio|biography|about)\b", re.I)),
]

# Titles of people who teach. Office managers, analysts, engineers... are left out.
_TEACHING_TITLE = re.compile(r"faculty|chair|instructor|professor|lecturer|dean|adjunct", re.I)

# Only what the profile says. Anything else leaves the flag empty (None), never False.
_UNDERGRAD_RESEARCH = re.compile(
    r"undergraduate (?:student )?research|student research"
    r"|research with (?:undergraduate )?students"
    r"|students in (?:my |his |her |their )?research",
    re.I,
)

# Directory department slugs and tags that fit each schedule department. A schedule
# department missing here is compared with the slug made from its own name.
DEPARTMENT_ALIASES: dict[str, set[str]] = {
    "Computer Science & Engineering": {
        "computer-science-engineering",
        "cse",
        "cs/se",
        "computer science & elec eng",
        "software engineering",
        "computer information tech",
    },
    "Mathematics": {"mathematics"},
    "Academic Success & Tutoring": {"academic success & interdisciplinary studies"},
}

# Common English nicknames that are not a prefix of the formal name. Prefixes
# (Brad / Bradley, Matt / Matthew) are handled by _same_given_name.
_NICKNAMES: dict[str, set[str]] = {
    "bill": {"william"},
    "will": {"william"},
    "bob": {"robert"},
    "bobby": {"robert"},
    "dave": {"david"},
    "dick": {"richard"},
    "rick": {"richard", "frederick", "eric"},
    "ted": {"edward", "theodore"},
    "ed": {"edward", "edwin"},
    "jim": {"james"},
    "jimmy": {"james"},
    "jack": {"john"},
    "mike": {"michael"},
    "nate": {"nathan", "nathaniel"},
    "liz": {"elizabeth"},
    "beth": {"elizabeth"},
    "betsy": {"elizabeth"},
    "kate": {"katherine", "kathryn", "catherine"},
    "katie": {"katherine", "kathryn", "catherine"},
    "peggy": {"margaret"},
    "maggie": {"margaret"},
    "tony": {"anthony"},
    "chuck": {"charles"},
    "charlie": {"charles"},
    "hank": {"henry"},
    "jake": {"jacob"},
    "joe": {"joseph"},
    "steve": {"stephen", "steven"},
    "sue": {"susan", "suzanne"},
    "becky": {"rebecca"},
    "sandy": {"sandra"},
    "jen": {"jennifer"},
    "jenny": {"jennifer"},
}

_SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def norm(s: str) -> str:
    """'Santa María, Karen E.' -> 'santa maria, karen e'."""
    ascii_ = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", ascii_.replace(".", "")).strip().lower()


def slug(s: str) -> str:
    """'Design & Construction Management' -> 'design-and-construction-management'."""
    return re.sub(r"[^a-z0-9]+", "-", norm(s).replace("&", " and ")).strip("-")


@dataclass(frozen=True)
class ScheduleName:
    """'Lawrence, Bradley W.' split like populate_db.split_name()."""

    full_name: str
    department: str
    last: str
    first: str | None
    middle: str | None

    @classmethod
    def parse(cls, full_name: str, department: str) -> ScheduleName:
        last, _, rest = full_name.partition(",")
        parts = rest.split()
        return cls(
            full_name,
            department,
            last.strip(),
            parts[0] if parts else None,
            " ".join(parts[1:]) or None,
        )


@dataclass(frozen=True)
class Match:
    schedule: ScheduleName
    profile: dict[str, Any] | None  # the directory entry; None when nothing is attached
    confidence: float
    reason: str


def directory_name(name: str) -> tuple[str, str | None, str | None]:
    """'David R. Peck' -> ('Peck', 'David', 'R.'). The last word is the last name
    (a suffix like 'Jr.' is skipped)."""
    parts = name.split()
    while len(parts) > 1 and norm(parts[-1]).strip(",") in _SUFFIXES:
        parts.pop()
    if len(parts) == 1:
        return parts[0], None, None
    return parts[-1], parts[0], " ".join(parts[1:-1]) or None


def is_teaching(profile: dict[str, Any]) -> bool:
    return bool(_TEACHING_TITLE.search(profile.get("job_title") or ""))


def _same_given_name(a: str, b: str) -> bool:
    """Brad / Bradley, Matt / Matthew, Bill / William (case already normalized)."""
    if a == b:
        return True
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 3 and long_.startswith(short):
        return True
    return long_ in _NICKNAMES.get(short, set()) or short in _NICKNAMES.get(long_, set())


def _last_name_fits(sched_last: str, profile_name: str) -> bool:
    """The directory name ends with the schedule's last name ('Karen Santa Maria')."""
    words = norm(profile_name).split()
    while len(words) > 1 and words[-1] in _SUFFIXES:
        words.pop()
    return " ".join(words).endswith(" " + norm(sched_last))


def _department_fits(department: str, profile: dict[str, Any]) -> bool:
    theirs = {norm(t) for t in profile.get("tags") or []} | set(profile.get("departments") or [])
    ours = DEPARTMENT_ALIASES.get(department, set()) | {slug(department), norm(department)}
    return bool(theirs & ours)


def _score(s: ScheduleName, profile: dict[str, Any]) -> tuple[float, str]:
    if not s.first or not _last_name_fits(s.last, profile["name"]):
        return 0.0, ""
    first = norm(directory_name(profile["name"])[1] or "")
    ours = norm(s.first)
    if first == ours:
        score, why = 1.0, "same first and last name"
    elif first and _same_given_name(first, ours):
        score, why = NICKNAME_SCORE, f"nickname {first!r} for {ours!r}"
    elif first and s.middle and any(_same_given_name(first, norm(m)) for m in s.middle.split()):
        score, why = NICKNAME_SCORE, f"goes by middle name {first!r}"
    else:
        return 0.0, ""
    if not _department_fits(s.department, profile):
        score, why = score * OTHER_DEPARTMENT_FACTOR, why + ", other department"
    return round(score, 2), why


def match_all(
    schedule: list[ScheduleName],
    profiles: list[dict[str, Any]],
    overrides: list[dict[str, Any]] | None = None,
) -> list[Match]:
    """One Match per schedule name. ``profile`` is set only when confidence >= 0.8."""
    by_url = {p["url"]: p for p in profiles}
    fixed = {(o["full_name"], o["department"]): o.get("directory_url") for o in overrides or []}
    out = []
    for s in schedule:
        key = (s.full_name, s.department)
        if key in fixed:
            url = fixed[key]
            if url is None:
                out.append(Match(s, None, 0.0, "override: no profile"))
            elif url in by_url:
                out.append(Match(s, by_url[url], 1.0, "override"))
            else:
                out.append(Match(s, None, 0.0, f"override points to unknown profile {url}"))
            continue
        scored = [(sc, why, p) for p in profiles for sc, why in [_score(s, p)] if sc > 0]
        if not scored:
            out.append(Match(s, None, 0.0, "not in the directory"))
            continue
        best = max(sc for sc, _, _ in scored)
        top = [(why, p) for sc, why, p in scored if sc == best]
        if len(top) > 1:
            names = ", ".join(p["name"] for _, p in top)
            out.append(Match(s, None, best, f"ambiguous: {names}"))
        elif best < MIN_CONFIDENCE:
            why, p = top[0]
            out.append(Match(s, None, best, f"low confidence with {p['name']} ({why})"))
        else:
            why, p = top[0]
            out.append(Match(s, p, best, why))
    return out


def profile_sources(profile: dict[str, Any]) -> dict[str, str]:
    """{kind: text} for all five kinds. A section the page does not have is ''."""
    found: dict[str, list[str]] = {k: [] for k in SOURCE_KINDS}
    for heading, value in (profile.get("sections") or {}).items():
        kind = next((k for k, rx in _HEADING_KINDS if rx.search(heading.strip(" :"))), None)
        if kind is None:
            continue
        body = "\n".join(value) if isinstance(value, list) else str(value)
        if body.strip():
            found[kind].append(body.strip())
    return {k: "\n\n".join(v) for k, v in found.items()}


def lists_undergrad_research(profile: dict[str, Any]) -> bool | None:
    """True only when the profile text says so; otherwise None (unknown, never guessed)."""
    return True if _UNDERGRAD_RESEARCH.search(profile.get("description") or "") else None
