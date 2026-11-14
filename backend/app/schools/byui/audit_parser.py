"""BYU-Idaho degree audit parser (AI-04).

Claude reads the PDF (`app.llm.audit`); this module adds what is specific to
BYU-Idaho: course codes are normalized with ENG-02's normalizer (`CSE111`,
`CSE 111-01` -> `CSE 111`) before validation, so a spacing difference never costs a
retry.
"""

from __future__ import annotations

from typing import Any

from app.contracts import DegreeAudit
from app.llm import audit as llm_audit
from app.schools.base import DegreeAuditParser
from app.schools.byui.parsing import ParseError, normalize_course_code


def _code(value: Any) -> Any:
    """Normalized code, or the value unchanged so validation reports it."""
    if not isinstance(value, str):
        return value
    try:
        return normalize_course_code(value).course_code
    except ParseError:
        return value


def normalize_codes(raw: dict[str, Any]) -> dict[str, Any]:
    for course in raw.get("courses") or []:
        if isinstance(course, dict):
            course["course_code"] = _code(course.get("course_code"))
            if course.get("equivalent_of") is not None:
                course["equivalent_of"] = _code(course["equivalent_of"])
    for req in raw.get("requirements") or []:
        if isinstance(req, dict):
            for key in ("options", "courses_counted"):
                if isinstance(req.get(key), list):
                    req[key] = [_code(c) for c in req[key]]
    return raw


class ByuiAuditParser(DegreeAuditParser):
    def __init__(self, caller: llm_audit.Caller = llm_audit.claude_caller) -> None:
        self._caller = caller

    def parse(self, pdf: bytes) -> DegreeAudit:
        return llm_audit.parse_audit_pdf(pdf, prepare=normalize_codes, caller=self._caller)
