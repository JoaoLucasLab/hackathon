"""AI-04: flags on a parsed or edited audit, and the confirm/save endpoint."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import audit_store, fixture_data
from app.api.audit import known_course_codes
from app.api.audit_validation import validate
from app.contracts import DegreeAudit
from app.main import app

KNOWN = known_course_codes()


def _raw() -> dict[str, Any]:
    return fixture_data.audit().model_dump(mode="json")


def _flags(raw: dict[str, Any], today: date | None = None) -> list[tuple[str, str]]:
    audit = DegreeAudit.model_validate(raw)
    flags = validate(audit, KNOWN, today or audit.audit_date, 30)
    return [(f.field, f.kind) for f in flags]


def _req_index(raw: dict[str, Any], status: str) -> int:
    return next(i for i, r in enumerate(raw["requirements"]) if r["status"] == status)


def test_fixture_audit_has_no_flags() -> None:
    assert _flags(_raw()) == []


def test_unmet_option_missing_from_this_semesters_list_is_flagged() -> None:
    raw = _raw()
    i = _req_index(raw, "not_met")
    raw["requirements"][i]["options"][0] = "MATH 999"
    audit = DegreeAudit.model_validate(raw)
    flags = validate(audit, KNOWN, audit.audit_date, 30)
    match = [f for f in flags if f.field == f"requirements[{i}].options[0]"]
    assert [f.kind for f in match] == ["unknown_course"]
    assert "may not be offered this term" in match[0].message


def test_options_of_a_complete_requirement_are_not_checked() -> None:
    raw = _raw()
    i = _req_index(raw, "complete")
    raw["requirements"][i]["options"] = ["CSE 999"]
    assert not [f for f in _flags(raw) if f[1] == "unknown_course"]


def test_courses_on_the_record_are_not_checked_against_this_semester() -> None:
    # Taken in an earlier term; it need not be offered in Winter 2027.
    raw = _raw()
    raw["courses"][0]["course_code"] = "CSE 999"
    i = _req_index(raw, "complete")
    raw["requirements"][i]["courses_counted"] = ["CSE 999"]
    assert not [f for f in _flags(raw) if f[1] == "unknown_course"]


def test_option_in_a_subject_the_catalog_does_not_hold_is_not_flagged() -> None:
    raw = _raw()
    i = _req_index(raw, "not_met")
    raw["requirements"][i]["options"][0] = "ART 130"
    assert not [f for f in _flags(raw) if f[1] == "unknown_course"]


def test_transfer_equivalent_is_not_checked_against_this_semester() -> None:
    raw = _raw()
    raw["courses"].append(
        {
            "course_code": "CS 142",
            "title": "Transfer course",
            "credits": 0,
            "grade": "A",
            "term": "Fall 2024",
            "status": "transfer",
            "equivalent_of": "CSE 998",
            "instructor": None,
        }
    )
    assert not [f for f in _flags(raw) if f[1] == "unknown_course"]


def test_earned_credits_below_course_total_is_a_mismatch() -> None:
    raw = _raw()
    raw["total_credits_earned"] = 1
    assert ("total_credits_earned", "credit_mismatch") in _flags(raw)


def test_needed_more_than_required_is_a_mismatch() -> None:
    raw = _raw()
    i = _req_index(raw, "not_met")
    raw["requirements"][i]["credits_needed"] = raw["requirements"][i]["credits_required"] + 5
    assert (f"requirements[{i}].credits_needed", "credit_mismatch") in _flags(raw)


def test_counted_courses_that_do_not_add_up_are_a_mismatch() -> None:
    raw = _raw()
    i = _req_index(raw, "complete")
    req = raw["requirements"][i]
    assert req["courses_counted"], "fixture needs a complete requirement with courses"
    req["credits_required"] += 3
    flags = _flags(raw)
    assert (f"requirements[{i}].credits_needed", "credit_mismatch") in flags


@pytest.mark.parametrize(
    ("change", "field_kind"),
    [
        ("complete_with_credits_needed", "status"),
        ("not_met_with_nothing_needed", "status"),
        ("in_progress_course_with_grade", "course"),
        ("complete_course_without_grade", "course"),
    ],
)
def test_contradictory_status_is_flagged(change: str, field_kind: str) -> None:
    raw = _raw()
    if change == "complete_with_credits_needed":
        i = _req_index(raw, "complete")
        raw["requirements"][i]["credits_needed"] = 2
        raw["requirements"][i]["credits_required"] = max(
            raw["requirements"][i]["credits_required"], 2
        )
        expected = f"requirements[{i}].status"
    elif change == "not_met_with_nothing_needed":
        i = _req_index(raw, "not_met")
        raw["requirements"][i]["credits_needed"] = 0
        expected = f"requirements[{i}].status"
    elif change == "in_progress_course_with_grade":
        raw["courses"][0]["status"] = "in_progress"
        expected = "courses[0].status"
    else:
        raw["courses"][0]["grade"] = None
        expected = "courses[0].status"
    assert (expected, "invalid_status") in _flags(raw)


def test_old_audit_is_flagged_stale() -> None:
    raw = _raw()
    audit_date = date.fromisoformat(raw["audit_date"])
    assert ("audit_date", "stale_audit") not in _flags(raw, audit_date + timedelta(days=30))
    assert ("audit_date", "stale_audit") in _flags(raw, audit_date + timedelta(days=31))


# --- PUT /api/audit ------------------------------------------------------------------


@pytest.fixture
def api() -> Iterator[TestClient]:
    client = TestClient(app)
    client.cookies.set("sid", "test-validation")
    yield client
    audit_store.forget("test-validation")


def test_put_recomputes_flags_and_ignores_client_flags(api: TestClient) -> None:
    raw = _raw()
    raw["audit_date"] = date.today().isoformat()
    raw["validation_flags"] = [{"field": "major", "kind": "made_up", "message": "x"}]
    i = _req_index(raw, "not_met")
    raw["requirements"][i]["options"][0] = "CSE 999"
    res = api.put("/api/audit", json=raw)
    assert res.status_code == 200
    kinds = {(f["field"], f["kind"]) for f in res.json()["validation_flags"]}
    assert kinds == {(f"requirements[{i}].options[0]", "unknown_course")}


def test_put_requires_a_track(api: TestClient) -> None:
    raw = _raw()
    raw["track"] = None
    res = api.put("/api/audit", json=raw)
    assert res.status_code == 422


def test_put_rejects_a_student_name_field(api: TestClient) -> None:
    raw = _raw()
    raw["student_name"] = "Test Person"
    assert api.put("/api/audit", json=raw).status_code == 422


def test_confirmed_audit_drives_remaining_requirements(api: TestClient) -> None:
    raw = _raw()
    i = _req_index(raw, "not_met")
    raw["requirements"][i]["status"] = "complete"
    raw["requirements"][i]["credits_needed"] = 0
    raw["requirements"][i]["options"] = []
    name = raw["requirements"][i]["name"]
    before = [r["name"] for r in api.get("/api/requirements/remaining").json()]
    assert name in before
    assert api.put("/api/audit", json=raw).status_code == 200
    after = [r["name"] for r in api.get("/api/requirements/remaining").json()]
    assert name not in after
