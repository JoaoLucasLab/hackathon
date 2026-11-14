"""AI-04: degree audit PDF -> `DegreeAudit`, on recorded Claude replies (no network).

Golden cases live in `fixtures/audits/<case>/`: `recorded_reply.json` (Claude's reply
for that audit) and `expected.json` (the hand-checked result). See
`fixtures/audits/README.md`.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
from typing import Any

import pytest

from app import config
from app.api import fixture_data
from app.api.audit import known_course_codes
from app.api.audit_validation import with_flags
from app.contracts import CourseRecordStatus, DegreeAudit
from app.llm import audit as llm_audit
from app.llm import client as llm_client
from app.schools.byui.audit_parser import ByuiAuditParser

PDF = b"%PDF-1.7 fake audit bytes for tests"


class Recorded:
    """A Caller that replays replies in order and keeps every request it got."""

    def __init__(self, replies: list[str | None]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> str | None:
        self.requests.append(params)
        return self.replies.pop(0)


def _fixture_raw() -> dict[str, Any]:
    raw = fixture_data.audit().model_dump(mode="json")
    raw.pop("validation_flags")
    return raw


def _reply(audit: dict[str, Any] | None, readable: bool = True) -> str:
    return json.dumps({"readable": readable, "audit": audit})


def _parse(replies: list[str | None]) -> tuple[DegreeAudit, Recorded]:
    caller = Recorded(replies)
    return ByuiAuditParser(caller=caller).parse(PDF), caller


def _has_pdf(params: dict[str, Any]) -> bool:
    """True when any message carries a document block or the PDF's base64 bytes."""
    encoded = base64.standard_b64encode(PDF).decode("ascii")
    for message in params["messages"]:
        content = message["content"]
        if isinstance(content, str):
            if encoded in content:
                return True
            continue
        if any(block.get("type") == "document" for block in content):
            return True
    return False


def test_fixture_reply_round_trips() -> None:
    expected = fixture_data.audit()
    audit, caller = _parse([_reply(_fixture_raw())])
    assert audit.major == expected.major
    assert audit.catalog_year == expected.catalog_year
    assert [c.course_code for c in audit.courses] == [c.course_code for c in expected.courses]
    assert [r.name for r in audit.requirements] == [r.name for r in expected.requirements]
    assert audit.validation_flags == []
    assert len(caller.requests) == 1


def test_request_sends_pdf_once_with_cached_prompt_and_schema() -> None:
    _, caller = _parse([_reply(_fixture_raw())])
    params = caller.requests[0]
    doc = params["messages"][0]["content"][0]
    assert doc["type"] == "document"
    assert doc["source"]["media_type"] == "application/pdf"
    assert params["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert params["model"] == llm_client.chat_model()
    assert params["output_config"]["format"]["type"] == "json_schema"


def test_schema_has_no_name_id_or_flags() -> None:
    schema = llm_audit.output_schema()
    audit_fields = set(schema["$defs"]["DegreeAudit"]["properties"])
    assert "validation_flags" not in audit_fields
    assert not {"name", "student_name", "student_id", "i_number", "email"} & audit_fields
    assert schema["$defs"]["DegreeAudit"]["additionalProperties"] is False


def test_course_codes_are_normalized() -> None:
    raw = _fixture_raw()
    raw["courses"][0]["course_code"] = "CSE110"
    raw["requirements"][0]["options"] = ["cse 111-01"]
    audit, caller = _parse([_reply(raw)])
    assert audit.courses[0].course_code == "CSE 110"
    assert audit.requirements[0].options == ["CSE 111"]
    assert len(caller.requests) == 1  # no retry needed for spacing


def test_requirement_ids_are_rebuilt_unique() -> None:
    raw = _fixture_raw()
    for req in raw["requirements"]:
        req["id"] = "x"
    audit, _ = _parse([_reply(raw)])
    ids = [r.id for r in audit.requirements]
    assert len(set(ids)) == len(ids)
    assert all(i != "x" for i in ids)


def test_in_progress_and_transfer_kept() -> None:
    raw = _fixture_raw()
    raw["courses"].append(
        {
            "course_code": "CS 140",
            "title": "Transfer Programming",
            "credits": 3,
            "grade": "A",
            "term": "Fall 2024",
            "status": "transfer",
            "equivalent_of": "CSE 110",
            "instructor": None,
        }
    )
    raw["courses"][1]["status"] = "in_progress"
    raw["courses"][1]["grade"] = None
    audit, _ = _parse([_reply(raw)])
    assert audit.courses[1].status == CourseRecordStatus.in_progress
    assert audit.courses[1].grade is None
    assert audit.courses[-1].status == CourseRecordStatus.transfer
    assert audit.courses[-1].equivalent_of == "CSE 110"


def test_invalid_reply_retries_once_without_the_pdf() -> None:
    bad = _fixture_raw()
    bad["courses"][0]["course_code"] = "not a course"
    audit, caller = _parse([_reply(bad), _reply(_fixture_raw())])
    assert len(caller.requests) == 2
    assert _has_pdf(caller.requests[0])
    retry = caller.requests[1]
    assert not _has_pdf(retry)
    assert "courses.0.course_code" in retry["messages"][0]["content"]
    assert audit.courses[0].course_code == "CSE 110"


def test_two_bad_replies_raise_parse_error() -> None:
    bad = _fixture_raw()
    bad["total_credits_earned"] = -3
    with pytest.raises(llm_audit.AuditParseError, match="couldn't read this audit"):
        _parse([_reply(bad), _reply(bad)])


def test_extra_field_like_student_name_is_rejected() -> None:
    bad = _fixture_raw()
    bad["student_name"] = "Test Person"
    with pytest.raises(llm_audit.AuditParseError):
        _parse([_reply(bad), _reply(copy.deepcopy(bad))])


@pytest.mark.parametrize("id_text", ["123456789", "123-45-6789", "123-456-789"])
def test_id_number_in_any_field_is_rejected(id_text: str) -> None:
    bad = _fixture_raw()
    bad["major"] = f"Computer Science (BS) {id_text}"
    audit, caller = _parse([_reply(bad), _reply(_fixture_raw())])
    assert len(caller.requests) == 2
    assert id_text not in audit.model_dump_json()


def test_not_an_audit_raises_without_retry() -> None:
    caller = Recorded([_reply(None, readable=False)])
    with pytest.raises(llm_audit.AuditParseError):
        ByuiAuditParser(caller=caller).parse(PDF)
    assert len(caller.requests) == 1


def test_refusal_raises() -> None:
    with pytest.raises(llm_audit.AuditParseError):
        _parse([None])


def test_missing_api_key_raises_parse_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    llm_client.get_client.cache_clear()
    with pytest.raises(llm_audit.AuditParseError):
        ByuiAuditParser().parse(PDF)


# --- Golden audits: recorded reply -> hand-checked expected JSON ----------------------

GOLDEN = sorted(p for p in (config.FIXTURES_DIR / "audits").iterdir() if p.is_dir())


def test_three_golden_audits_exist() -> None:
    assert len(GOLDEN) >= 3


@pytest.mark.parametrize("case", GOLDEN, ids=lambda p: p.name)
def test_golden_audit_matches_expected(case: Path) -> None:
    reply = (case / "recorded_reply.json").read_text(encoding="utf-8")
    expected = DegreeAudit.model_validate_json((case / "expected.json").read_text("utf-8"))
    audit, caller = _parse([reply])
    audit = with_flags(audit, known_course_codes(), audit.audit_date, 30)
    assert audit == expected
    assert len(caller.requests) == 1


def test_golden_transfer_keeps_equivalents() -> None:
    path = config.FIXTURES_DIR / "audits/transfer-student/expected.json"
    expected = json.loads(path.read_text())
    transfers = [c for c in expected["courses"] if c["status"] == "transfer"]
    assert transfers and all(c["equivalent_of"] for c in transfers)


def test_golden_missing_track_stays_unknown() -> None:
    expected = json.loads(
        (config.FIXTURES_DIR / "audits/software-engineering-minor/expected.json").read_text()
    )
    assert expected["track"] is None
