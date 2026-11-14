#!/usr/bin/env python3
"""Scrape every BYU-Idaho faculty profile under /directories/, including the
biography sections (education, certifications, experience, etc.).

There is no public "list all" endpoint: /directories/ is just a landing page,
its RSS feeds are empty, and the full employee directory needs a church login
(which we never use). Profiles are reachable from each department's faculty
page, so we crawl:

  /directories/colleges-and-departments -> department home pages
    -> any link with "faculty" in it -> /directories/<person> links
      -> each profile page (parsed)

Rules it follows (see AGENTS.md):
- Public pages only. No login, no Authorization header, no cookies at all.
  It stops on a 401 or 403 or a redirect to a login page.
- At least DELAY_S (10) seconds between requests: www.byui.edu asks for
  Crawl-delay: 10. A full run takes a few hours, so run it only when the
  data needs refreshing, and one copy at a time.
- No HTML is saved; the only output is the JSON file. Each profile keeps its
  source URL and fetched-at time.
- No LinkedIn: LinkedIn links and sections are dropped before saving.
- One bad page is logged and skipped; the run prints succeeded / failed / skipped.

Usage:
    python3 scripts/scrape_faculty.py                 # writes scripts/out/faculty.json
    python3 scripts/scrape_faculty.py --limit 5       # first 5 profiles, to debug the parser
    python3 scripts/scrape_faculty.py --reclean scripts/out/faculty.json
        # no network: re-applies the cleaning (LinkedIn, fetched_at) to a saved file
Needs:  pip install beautifulsoup4 (only for scraping; --reclean uses the standard library)
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BASE = "https://www.byui.edu"
DELAY_S = 10.0  # robots.txt on www.byui.edu: Crawl-delay: 10
USER_AGENT = "course-planner-hackathon/0.1 (student hackathon project)"
OUT = Path(__file__).resolve().parent / "out" / "faculty.json"

SKIP_DEPT = re.compile(
    r"/(directories|search|apply|about|admissions|giving|news|events|"
    r"academics|student-life|a-z-index|web-maintenance|legal|contact|"
    r"copyright|speeches|whatsapp|campus-tours)(/|$)"
)
LINKEDIN = re.compile(r"linkedin", re.IGNORECASE)


class StopScrape(Exception):
    """The site answered in a way that means we must stop (not public, login page)."""


class _NoCookies(urllib.request.BaseHandler):
    """Strips any Cookie or Authorization header before a request leaves."""

    def http_request(self, req: urllib.request.Request) -> urllib.request.Request:
        for h in ("Cookie", "Authorization"):
            req.remove_header(h)
        return req

    https_request = http_request


class Fetcher:
    def __init__(self) -> None:
        self.opener = urllib.request.build_opener(_NoCookies())
        self.opener.addheaders = [("User-Agent", USER_AGENT)]
        self._last = 0.0
        self.requests = 0

    def _wait(self) -> None:
        gap = time.monotonic() - self._last
        if gap < DELAY_S:
            time.sleep(DELAY_S - gap)
        self._last = time.monotonic()

    def get(self, url: str) -> str | None:
        """The page's HTML, or None when this one page failed (logged)."""
        self._wait()
        try:
            resp = self.opener.open(url, timeout=30)
        except urllib.error.HTTPError as e:
            if e.code in (401, 403):
                raise StopScrape(f"HTTP {e.code} on {url}: not a public page. Stopping.") from e
            print(f"  ! {url}: HTTP {e.code}")
            return None
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  ! {url}: {e}")
            return None
        self.requests += 1
        final = resp.geturl().lower()
        if "login" in final or "saml" in final or "signin" in final:
            raise StopScrape(f"Redirected to a login page ({resp.geturl()}). Stopping.")
        return resp.read().decode("utf-8", "replace")


def links(html: str, prefix: str) -> set[str]:
    return {m.rstrip("/") for m in re.findall(rf'href="({re.escape(prefix)}[^"#?]*)"', html)}


def profile_links(html: str) -> set[str]:
    # Tag pages (e.g. /directories/cse-1) and nested paths get weeded out later:
    # parse_profile() returns None for anything that isn't an employee page.
    return {
        u
        for u in links(html, BASE + "/directories/")
        if "/" not in u[len(BASE + "/directories/") :]
        and not u.endswith("colleges-and-departments")
    }


def text(el: Any) -> str | None:
    return re.sub(r"\s+", " ", el.get_text(" ", strip=True)).strip() if el else None


def parse_sections(bio: Any) -> dict[str, Any]:
    """Split the biography into {heading: [bullet items]} or {heading: "paragraph text"}."""
    sections: dict[str, Any] = {}
    current: str | None = None
    buf: list[str | None] = []
    is_list = False

    def flush() -> None:
        items = [x for x in buf if x]
        if current is None and not items:
            return
        key = current or "Description"
        sections[key] = items if is_list else "\n\n".join(items)

    for el in bio.find_all(["h1", "h2", "h3", "h4", "p", "ul", "ol"], recursive=False) or []:
        if el.name in ("h1", "h2", "h3", "h4"):
            flush()
            current, buf, is_list = text(el), [], False
        elif el.name in ("ul", "ol"):
            if not is_list:  # switch to list mode, keeping any non-empty text before it
                buf, is_list = [x for x in buf if x], True
            buf.extend(text(li) for li in el.find_all("li"))
        else:
            buf.append(text(el))
    flush()
    return sections


def parse_image(soup: Any) -> tuple[str | None, str | None, str | None]:
    """Return (image_url, image_original_url, alt).

    The <img src> is a blank lazy-load placeholder (data:image/svg+xml), so the
    real 240x240 URL comes from data-src. The CDN URL wraps the full-size S3
    original in its ?url= parameter.
    """
    img = soup.select_one(".EmployeePage-image img")
    if not img:
        return None, None, None
    src = img.get("data-src") or img.get("src")
    if not src or src.startswith("data:"):
        return None, None, img.get("alt")
    original = urllib.parse.parse_qs(urllib.parse.urlparse(src).query).get("url", [None])[0]
    if original and original.startswith("http://"):
        original = "https://" + original[len("http://") :]
    return src, original, img.get("alt")


def parse_profile(url: str, html: str) -> dict[str, Any] | None:
    from bs4 import BeautifulSoup  # only needed when scraping

    soup = BeautifulSoup(html, "html.parser")
    info = soup.select_one(".EmployeePage-info")
    if not info:
        return None  # not a person (tag page, 404, etc.)

    email = info.select_one(".EmployeePage-info-email a")
    phones = [a.get_text(strip=True) for a in info.select(".EmployeePage-phoneNumber a")]
    extra_links = {
        a.get_text(strip=True): a["href"] for a in info.select(".EmployeePage-info-links a[href]")
    }
    bio = soup.select_one(".EmployeePage-fullBiography")
    image_url, image_original, image_alt = parse_image(soup)

    return {
        "name": text(info.select_one(".EmployeePage-info-name")),
        "url": url,
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "job_title": text(info.select_one(".EmployeePage-info-jobTitle")),
        "email": email.get_text(strip=True) if email else None,
        "office": text(info.select_one(".EmployeePage-info-address")),
        "phones": phones,
        "links": extra_links,
        "image_url": image_url,
        "image_original_url": image_original,
        "image_alt": image_alt,
        "sections": parse_sections(bio) if bio else {},
        "description": bio.get_text("\n", strip=True) if bio else None,
        "tags": [a.get_text(strip=True) for a in soup.select(".ListTags-items a")],
    }


def clean_profile(p: dict[str, Any]) -> dict[str, Any]:
    """Drop everything LinkedIn (AGENTS.md: no LinkedIn or personal social media)."""
    p["links"] = {
        k: v for k, v in p["links"].items() if not (LINKEDIN.search(k) or LINKEDIN.search(v))
    }
    sections: dict[str, Any] = {}
    for heading, value in p["sections"].items():
        if LINKEDIN.search(heading):
            continue
        if isinstance(value, list):
            value = [x for x in value if not LINKEDIN.search(x)]
        else:
            value = "\n\n".join(x for x in value.split("\n\n") if not LINKEDIN.search(x))
        if value:
            sections[heading] = value
    p["sections"] = sections
    if p.get("description"):
        p["description"] = "\n".join(
            line for line in p["description"].split("\n") if not LINKEDIN.search(line)
        )
    return p


def write_json(path: Path, data: list[dict[str, Any]]) -> None:
    tmp = path.with_suffix(".new.json")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(tmp, path)  # never leave a half-written backup


def reclean(path: Path) -> None:
    """Re-apply clean_profile() to a saved file. Profiles without fetched_at get the
    file's modified time, the closest known time for a file saved during the run."""
    data = json.loads(path.read_text())
    mtime = datetime.fromtimestamp(path.stat().st_mtime, UTC).isoformat(timespec="seconds")
    for p in data:
        p.setdefault("fetched_at", mtime)
        clean_profile(p)
    write_json(path, data)
    print(f"{len(data)} profiles cleaned -> {path}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, default=OUT)
    ap.add_argument("--limit", type=int, help="fetch at most this many profiles")
    ap.add_argument("--reclean", type=Path, metavar="FILE", help="clean a saved file, no network")
    args = ap.parse_args()

    if args.reclean:
        reclean(args.reclean)
        return 0

    f = Fetcher()
    ok = failed = skipped = 0
    out: list[dict[str, Any]] = []
    partial = args.out.with_suffix(".new.json")
    try:
        index = f.get(BASE + "/directories/colleges-and-departments") or ""
        depts = sorted(u for u in links(index, BASE + "/") if u != BASE and not SKIP_DEPT.search(u))
        print(f"{len(depts)} departments")

        people: dict[str, set[str]] = {}  # profile url -> department slugs
        for dept in depts:
            home = f.get(dept) or ""
            pages = {u for u in links(home, dept) if "faculty" in u.lower()}
            found = profile_links(home)
            for page in pages:
                found |= profile_links(f.get(page) or "")
            print(f"{dept}: {len(found)} profile links ({len(pages)} faculty pages)")
            for u in found:
                people.setdefault(u, set()).add(dept.rsplit("/", 1)[-1])

        todo = sorted(people.items())[: args.limit]
        print(f"\nFetching {len(todo)} profiles (~{len(todo) * int(DELAY_S) // 60} min)")
        for i, (url, depts_of) in enumerate(todo, 1):
            html = f.get(url)
            if html is None:
                failed += 1
            elif (profile := parse_profile(url, html)) is None:
                skipped += 1  # not a person
            else:
                profile["departments"] = sorted(depts_of)
                out.append(clean_profile(profile))
                ok += 1
            if i % 50 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)} fetched, {len(out)} profiles")
                partial.write_text(json.dumps(out, indent=2, ensure_ascii=False))  # progress
    except StopScrape as e:
        print(f"\nSTOP: {e}", file=sys.stderr)
        print(f"Kept the last good {args.out.name}; partial in {partial.name}.", file=sys.stderr)
        print(f"succeeded {ok} / failed {failed} / skipped {skipped}")
        return 2

    write_json(args.out, out)
    partial.unlink(missing_ok=True)
    print(f"\n{len(out)} profiles -> {args.out} ({f.requests} requests)")
    print(f"succeeded {ok} / failed {failed} / skipped {skipped}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
