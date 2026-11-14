"""Rate My Professors link (DATA-05).

A plain search link the student opens in their own browser. The backend never sends
a request to ratemyprofessors.com and the app shows none of its data (AGENTS.md).
The school id lives in ``config.yaml`` (``rmp_school_id``); ``ByuiRules.rmp_link``
passes it in.
"""

from __future__ import annotations

from urllib.parse import quote

_BASE = "https://www.ratemyprofessors.com/search/professors"


def rmp_link(first: str, last: str, school_id: str = "") -> str:
    """``.../search/professors/<RMP_SCHOOL_ID>?q=<First>%20<Last>``; without a school
    id the link searches every school."""
    path = f"{_BASE}/{quote(school_id)}" if school_id else _BASE
    return f"{path}?q={quote(' '.join(x for x in (first, last) if x))}"
