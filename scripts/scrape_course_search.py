#!/usr/bin/env python3
"""Standalone test scraper for BYU-Idaho Public Course Search.

Fetches the public class schedule (no login) for a few subjects and writes one
JSON file so the team can inspect the data. This is a throwaway test, not the
DATA-03 importer: it uses only the standard library and does not go through
PublicHttpClient (DATA-02 does not exist yet).

Rules it follows (see AGENTS.md):
- Public pages only. It never sends a username, password or Authorization
  header, and stops if the site redirects to a login page.
- The only cookie sent is the anonymous ASP.NET_SessionId that the page gives
  every visitor. Each subject starts with an empty cookie jar.
- At least DELAY_S seconds between requests.
- No HTML is saved to disk; the only output is the JSON file.
- Meeting times are kept as the raw strings ("TR 12:45-01:45PM"); turning them
  into real times is ENG-02's parser's job.
- Course requisites (the "Course Requisites" button) are fetched once per course
  and saved row by row with their OR/AND connectors, group and requisite type.
  Building the AND/OR tree from them is ENG-04's job.

Usage:
    python3 scripts/scrape_course_search.py                      # the SUBJECTS list
    python3 scripts/scrape_course_search.py --subjects CSE --limit 5
    python3 scripts/scrape_course_search.py --subjects ALL       # every subject (slow)
"""

from __future__ import annotations

import argparse
import html
import http.cookiejar
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path

URL = "https://student.byui.edu/ICS/Class_Schedule/"
USER_AGENT = "course-planner-hackathon/0.1 (student hackathon project)"
DELAY_S = 2.0
ALLOWED_COOKIES = {"ASP.NET_SessionId"}
# Login fields of the portal's sidebar; never sent.
NEVER_SEND = {"userName", "password", "q"}

BLOCK_TERMS = {
    "Winter First Block": "2027;WI;W1",
    "Winter Second Block": "2027;WI;W2",
}

# Subjects (discipline codes from the Course Search dropdown) to scrape.
SUBJECTS = ["CSE", "CIT", "MATH"]

SEARCH_PREFIX = "pg0$V$tabSearch$"
REQ_BUTTON = "pg0_V_lnkbCourseRequisites"


class StopScrape(Exception):
    """The site answered in a way that means we must not continue."""


class LostList(Exception):
    """The results list is gone, so no further section of this subject can be opened."""


# --------------------------------------------------------------------------- HTTP


class Session:
    """One anonymous browsing session: empty cookie jar, throttled, no auth."""

    def __init__(self) -> None:
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))
        self.opener.addheaders = [("User-Agent", USER_AGENT)]
        self._last = 0.0
        self.requests = 0

    def _wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < DELAY_S:
            time.sleep(DELAY_S - gap)
        self._last = time.monotonic()

    def _check_cookies(self) -> None:
        extra = {c.name for c in self.jar} - ALLOWED_COOKIES
        for name in extra:
            # Drop anything that is not the anonymous session cookie before it can be sent.
            for c in list(self.jar):
                if c.name == name:
                    self.jar.clear(c.domain, c.path, c.name)

    def fetch(self, data: dict[str, str] | None = None) -> str:
        self._check_cookies()
        self._wait()
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        req = urllib.request.Request(URL, data=body)
        if body is not None:
            req.add_header("Content-Type", "application/x-www-form-urlencoded")
        try:
            resp = self.opener.open(req, timeout=60)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise StopScrape(f"HTTP {e.code}: the page is not public. Stopping.") from e
            raise
        self.requests += 1
        final = resp.geturl().lower()
        if "login" in final or "saml" in final:
            raise StopScrape(f"Redirected to a login page ({resp.geturl()}). Stopping.")
        text = resp.read().decode("utf-8", "replace")
        if "<title>\n Guest Home" in text or "Guest Home - Main View" in text:
            raise StopScrape(
                "The site returned Guest Home instead of Course Search (session lost)."
            )
        return text


# ----------------------------------------------------------------------- HTML helpers


def clean(s: str | None) -> str:
    if s is None:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).strip()


def attr(tag: str, name: str) -> str | None:
    m = re.search(rf'\b{name}="([^"]*)"', tag)
    return html.unescape(m.group(1)) if m else None


def form_fields(page: str) -> dict[str, str]:
    """Serialize the page's form like a browser would, minus buttons and login fields."""
    data: dict[str, str] = {}
    for m in re.finditer(r"<input\b[^>]*>", page):
        tag = m.group(0)
        name, kind = attr(tag, "name"), (attr(tag, "type") or "text").lower()
        if not name or name in NEVER_SEND or kind in ("submit", "button", "password", "image"):
            continue
        if kind == "checkbox":
            if "checked" in tag:
                data[name] = "on"
            continue
        data[name] = attr(tag, "value") or ""
    for m in re.finditer(r'<select\b[^>]*name="([^"]+)"[^>]*>(.*?)</select>', page, re.S):
        name, body = html.unescape(m.group(1)), m.group(2)
        sel = re.search(r'<option[^>]*selected="selected"[^>]*value="([^"]*)"', body) or re.search(
            r'<option[^>]*value="([^"]*)"', body
        )
        data[name] = html.unescape(sel.group(1)) if sel else ""
    data.pop("__EVENTTARGET", None)
    data.pop("__EVENTARGUMENT", None)
    return data


def postback(page: str, target: str, extra: dict[str, str] | None = None) -> dict[str, str]:
    data = form_fields(page)
    data["__EVENTTARGET"] = target
    data["__EVENTARGUMENT"] = ""
    data.update(extra or {})
    return data


def select_options(page: str, name: str) -> list[tuple[str, str]]:
    m = re.search(rf'<select\b[^>]*name="{re.escape(name)}"[^>]*>(.*?)</select>', page, re.S)
    if not m:
        return []
    return [
        (html.unescape(v), clean(t))
        for v, t in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>([^<]*)', m.group(1))
    ]


# ---------------------------------------------------------------------------- parsing


def parse_code(text: str) -> tuple[str, str]:
    """'CSE  110-01' -> ('CSE 110', '01')."""
    m = re.match(r"([A-Z]+)\s*(\d+[A-Z]?)-(\w+)", text.strip())
    if not m:
        return clean(text), ""
    return f"{m.group(1)} {m.group(2)}", m.group(3)


def parse_date(mmddyyyy: str) -> str:
    return datetime.strptime(mmddyyyy.strip(), "%m/%d/%Y").date().isoformat()


def parse_list(page: str) -> list[dict]:
    rows = []
    tbody = re.search(r'<table id="tableCourses".*?<tbody>(.*?)</tbody>', page, re.S)
    if not tbody:
        return rows
    for tr in re.findall(r"<tr>(.*?)</tr>", tbody.group(1), re.S):
        link = re.search(r'id="(pg0_V_rptCourses_ctl\d+_lnkCourse)"[^>]*>([^<]*)</a>', tr)
        if not link:
            continue
        tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)
        course, section = parse_code(clean(link.group(2)))
        meetings = []
        for li in re.findall(r"<li>(.*?)</li>", tr, re.S):
            head = clean(li.split("<div>")[0])
            divs = [clean(d) for d in re.findall(r"<div>(.*?)</div>", li, re.S)]
            dates = re.match(r"\((\S+)\s*-\s*(\S+)\)", divs[0]) if divs else None
            days_time = re.match(r"([MTWRFSU]*)\s*(\S+)$", head)
            days, time_raw = (days_time.group(1), days_time.group(2)) if days_time else ("", head)
            no_time = time_raw.startswith("00:00-00:00")
            meetings.append(
                {
                    "raw": head,
                    "days": days,
                    "time_raw": None if no_time else time_raw,
                    "start_date": parse_date(dates.group(1)) if dates else None,
                    "end_date": parse_date(dates.group(2)) if dates else None,
                    "room": next((d for d in divs[1:] if d), None),
                }
            )
        block = re.search(r"class='subsess'>(.*?)</div>", tr, re.S)
        block_label = clean(block.group(1)) if block else None
        remarks = [
            clean(r) for r in re.findall(r"class='remark'[^>]*>(.*?)</", tr, re.S) if clean(r)
        ]
        rows.append(
            {
                "_target": link.group(1).replace(
                    "_", "$"
                ),  # pg0_V_rptCourses_ctl01_lnkCourse -> pg0$V$...
                "course": course,
                "section": section,
                "title": clean(tds[2]) if len(tds) > 2 else "",
                "credits": float(clean(tds[3]))
                if len(tds) > 3 and re.match(r"^\d", clean(tds[3]))
                else None,
                "meetings": meetings,
                "block": block_label,
                "class_type": clean(re.search(r'litSubProgValue">(.*?)</td>', tr, re.S).group(1))
                if "litSubProgValue" in tr
                else None,
                "delivery_method": clean(
                    re.search(r'litLocatioonValue">(.*?)</td>', tr, re.S).group(1)
                )
                if "litLocatioonValue" in tr
                else None,
                "remarks": remarks,
            }
        )
    return rows


def span(page: str, span_id: str) -> str:
    m = re.search(rf'id="{span_id}"[^>]*>(.*?)</span>', page, re.S)
    return clean(m.group(1)) if m else ""


def parse_detail(page: str) -> dict:
    h5 = re.search(r'<div id="pg0_V_divCourseDetails">.*?<h5>(.*?)</h5>', page, re.S)
    code_m = re.search(r"\(([^()]*)\)\s*$", clean(h5.group(1))) if h5 else None
    instructors = []
    for m in re.finditer(r'lblInstructorValue"></span>\s*([^<]+?)\s*<', page):
        name = clean(m.group(1))
        if name:
            instructors.append(name)
    status_raw = span(page, "pg0_V_lblStatusValue")
    seats = re.match(r"(\w+)\s*\((\d+) out of (\d+) seats\)", status_raw)
    note = span(page, "pg0_V_lblNotesValue")
    detail_meetings = []
    table = re.search(r"Course Schedules.*?<tbody>(.*?)</tbody>", page, re.S)
    if table:
        for tr in re.findall(r"<tr>(.*?)</tr>", table.group(1), re.S):
            tds = [clean(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) == 3:
                detail_meetings.append({"day_time": tds[0], "dates": tds[1], "location": tds[2]})
    areas = span(page, "pg0_V_lblCourseAreaValue")
    return {
        "code_on_page": parse_code(code_m.group(1)) if code_m else None,
        "instructors": instructors,
        "status_raw": status_raw,
        "status": seats.group(1).lower() if seats else None,
        "seats_open": int(seats.group(2)) if seats else None,
        "seats_total": int(seats.group(3)) if seats else None,
        "department": span(page, "pg0_V_lblDepartmentValue"),
        "grading": span(page, "pg0_V_lblMethodDescriptionValue"),
        "course_areas": [a.strip() for a in areas.split(",") if a.strip()],
        "note": None if note.startswith("No note is available") else note,
        "description": span(page, "pg0_V_lblCourseDescValue"),
        "locations": detail_meetings,
    }


REQ_COURSE = re.compile(
    r"Course\s+([A-Z]+)\s+(\d+[A-Z]?)\s+must be taken(?:\s+with a grade of\s+(\S+)\s+or better)?",
    re.I,
)


def parse_requisites(page: str) -> dict:
    """Course Requisites table -> rows kept as on the page, plus a readable expression.

    The page lists requisites in order, with connector rows (OR / AND, sometimes
    parentheses) between them. Building the real AND/OR tree is ENG-04's job;
    here every row is saved as-is so nothing is lost.
    """
    table = re.search(r'<table id="tableReq".*?<tbody>(.*?)</tbody>', page, re.S)
    items: list[dict] = []
    tokens: list[str] = []
    pending: list[str] = []  # connectors/parentheses seen since the last requisite
    if table:
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", table.group(1), re.S):
            tds = [clean(td) for td in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S)]
            if len(tds) < 4:
                continue
            cond, group, req_type, text = tds[:4]
            if not req_type and not text:
                if cond:
                    pending.append(cond.upper())
                    tokens.append(cond.upper())
                continue
            m = REQ_COURSE.search(text)
            items.append(
                {
                    "connector_before": " ".join(pending) or None,
                    "condition": cond or None,
                    "group": group or None,
                    "type": req_type,
                    "text": text,
                    "course": f"{m.group(1).upper()} {m.group(2).upper()}" if m else None,
                    "min_grade": m.group(3) if m else None,
                }
            )
            if cond:
                tokens.append(cond.upper())
            label = items[-1]["course"] or text
            if items[-1]["min_grade"]:
                label += f" ({items[-1]['min_grade']} or better)"
            tokens.append(f"[{group}] {req_type}: {label}" if group else f"{req_type}: {label}")
            pending = []
    return {"requisites": items, "requisites_expression": " ".join(tokens) or None}


# ----------------------------------------------------------------------------- scrape


def search(session: Session, term: str, subject: str) -> str:
    landing = session.fetch()
    data = form_fields(landing)
    data.update(
        {
            SEARCH_PREFIX + "ddlTermSearch": term,
            SEARCH_PREFIX + "ddlDeliveryMethod": "",
            SEARCH_PREFIX + "ddlDept": "",
            SEARCH_PREFIX + "ddlDiscipline": subject,
            SEARCH_PREFIX + "txtTitleRestrictor": "",
            SEARCH_PREFIX + "txtCourseRestrictor": "",
            SEARCH_PREFIX + "ddlDivisionSearch": "",
            SEARCH_PREFIX + "btnSearch": "Search",
        }
    )
    page = session.fetch(data)
    if "lnkShowAll" in page:
        page = session.fetch(postback(page, "pg0$V$lnkShowAll"))
    return page


def back_to_list(session: Session, page: str) -> str:
    """Click "Back to search results" until the results list is showing again.

    From a requisites page, "Back" lands on the course details page, not on the
    list, so it can take two clicks. The next section's link only works on the list.
    """
    for _ in range(3):
        if 'id="tableCourses"' in page:
            return page
        if "pg0_V_lnkBack" not in page:
            break
        page = session.fetch(postback(page, "pg0$V$lnkBack"))
    if 'id="tableCourses"' in page:
        return page
    raise LostList("could not get back to the results list")


def scrape_subject(
    term: str, subject: str, limit: int | None, requisites: dict[str, dict], stats: dict
) -> list[dict]:
    """Scrape one subject.

    `requisites` is shared across subjects: course code -> parsed requisites.
    """
    session = Session()
    list_page = search(session, term, subject)
    rows = parse_list(list_page)
    if "No courses" in list_page and not rows:
        print(f"  {subject}: no sections")
        return []
    if limit:
        rows = rows[:limit]
    print(f"  {subject}: {len(rows)} sections on the list page")

    out = []
    current = list_page  # the page whose form state the next detail postback uses
    for i, row in enumerate(rows, 1):
        target = row.pop("_target")
        key = f"{row['course']}-{row['section']}"
        fetched_at: str | None = datetime.now(UTC).isoformat(timespec="seconds")
        try:
            detail_page = session.fetch(postback(current, target))
            back_from = detail_page
            # Requisites belong to the course, so they are fetched once for its first section.
            if REQ_BUTTON in detail_page and row["course"] not in requisites:
                req_page = session.fetch(postback(detail_page, "pg0$V$lnkbCourseRequisites"))
                requisites[row["course"]] = parse_requisites(req_page)
                stats["requisite_pages"] += 1
                back_from = req_page
            current = back_to_list(session, back_from)
            detail = parse_detail(detail_page)
            if detail.pop("code_on_page") != (row["course"], row["section"]):
                raise ValueError("detail page is for a different section")
            if REQ_BUTTON in detail_page:
                detail.update(requisites[row["course"]])
            else:
                # No "Course Requisites" button on the page: the site lists none.
                detail.update({"requisites": [], "requisites_expression": None})
            stats["ok"] += 1
        except (StopScrape, LostList):
            raise
        except Exception as e:  # one bad page is logged and skipped
            print(f"    skipped {key}: {e}", file=sys.stderr)
            stats["failed"] += 1
            detail = {}
            fetched_at = None
        out.append(
            {
                **row,
                "term": term,
                "term_code": BLOCK_TERMS.get(row["block"] or "", term),
                **detail,
                "seats_as_of": fetched_at if detail.get("status_raw") else None,
                "source_url": URL,
                "source_note": f"Public Course Search, term {term}, subject {subject}, "
                f"section {row['course']}-{row['section']}",
                "fetched_at": fetched_at,
            }
        )
        if i % 10 == 0:
            print(f"    {i}/{len(rows)}")
    stats["requests"] += session.requests
    return out


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument(
        "--term", default="2027;WI", help="term code (default 2027;WI; includes both blocks)"
    )
    ap.add_argument(
        "--subjects", nargs="+", default=SUBJECTS, help="override SUBJECTS; ALL for every subject"
    )
    ap.add_argument("--limit", type=int, help="max sections per subject (for quick tests)")
    ap.add_argument(
        "--out", default=str(Path(__file__).resolve().parent / "out" / "course_search.json")
    )
    args = ap.parse_args()
    # Show progress lines right away, even when output is not a terminal (IDE run panel, pipe).
    sys.stdout.reconfigure(line_buffering=True)  # type: ignore[union-attr]

    subjects = args.subjects
    if subjects == ["ALL"]:
        landing = Session().fetch()
        subjects = [v for v, _ in select_options(landing, SEARCH_PREFIX + "ddlDiscipline") if v]

    stats = {"ok": 0, "failed": 0, "requests": 0, "requisite_pages": 0}
    requisites: dict[str, dict] = {}
    sections: list[dict] = []
    started = datetime.now(UTC)
    complete = True  # False when the run stopped or a subject failed
    print(f"Term {args.term}, subjects: {' '.join(subjects)}", flush=True)
    for subject in subjects:
        try:
            sections += scrape_subject(args.term, subject, args.limit, requisites, stats)
        except StopScrape as e:
            print(f"STOPPED: {e}", file=sys.stderr)
            complete = False
            break
        except Exception as e:  # one bad subject is logged and skipped
            print(f"  {subject}: failed ({e})", file=sys.stderr)
            complete = False

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "source": URL,
                "term": args.term,
                "subjects": subjects,
                "scraped_at": started.isoformat(timespec="seconds"),
                "count": len(sections),
                "sections": sections,
            },
            indent=2,
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    print(
        f"Done: {stats['ok']} sections parsed, {stats['failed']} failed, "
        f"{stats['requisite_pages']} requisite pages fetched, {stats['requests']} requests. "
        f"Wrote {out}"
    )
    # Exit code 1 when data is missing, so scripts/refresh_data.py does not load a
    # partial file into the database.
    return 0 if complete else 1


if __name__ == "__main__":
    sys.exit(main())
