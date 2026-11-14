"""ENG-01: every contract model exists, exports JSON Schema, and every stub
endpoint returns data that validates against its response model."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import TypeAdapter, ValidationError

from app.contracts import (
    REQUIRED_MODELS,
    AuditRequirement,
    BuildSchedulesResponse,
    ChatEvent,
    ChatHistory,
    ConstraintSet,
    DegreeAudit,
    EmailDraft,
    FavoriteProfessor,
    Meeting,
    MentorMatch,
    PrereqAll,
    Professor,
    SessionResponse,
    Student,
)
from app.main import app

client = TestClient(app)


@pytest.mark.parametrize("name", sorted(REQUIRED_MODELS))
def test_model_exports_json_schema(name: str) -> None:
    schema = REQUIRED_MODELS[name].model_json_schema()
    assert schema["type"] == "object"
    json.dumps(schema)  # serializable


def test_prereq_expression_round_trip() -> None:
    data = {
        "type": "all",
        "items": [
            {
                "type": "any",
                "items": [
                    {"type": "course", "course_code": "CSE 110"},
                    {"type": "course", "course_code": "CS 101"},
                    {"type": "condition", "text": "PathwayConnect"},
                ],
            }
        ],
    }
    expr = PrereqAll.model_validate(data)
    assert PrereqAll.model_validate_json(expr.model_dump_json()) == expr


@pytest.mark.parametrize("field", ["name", "student_name", "student_id", "byui_id"])
def test_audit_and_student_reject_personal_fields(field: str) -> None:
    audit = client.post("/api/audit/sample").json()
    with pytest.raises(ValidationError):
        DegreeAudit.model_validate({**audit, field: "x"})
    with pytest.raises(ValidationError):
        Student.model_validate({"id": "s", field: "x"})


def test_meeting_rejects_start_after_end() -> None:
    with pytest.raises(ValidationError):
        Meeting.model_validate(
            {
                "days": ["T"],
                "start_time": "13:45",
                "end_time": "12:45",
                "start_date": "2027-01-06",
                "end_date": "2027-04-08",
            }
        )


def test_constraint_set_rejects_inverted_credit_range() -> None:
    with pytest.raises(ValidationError):
        ConstraintSet(credit_min=15, credit_max=12)


def test_course_code_pattern() -> None:
    TypeAdapter(AuditRequirement).validate_python(
        {
            "id": "r",
            "group": "g",
            "name": "n",
            "status": "not_met",
            "credits_required": 3,
            "credits_needed": 3,
            "options": ["MATH 221A"],
        }
    )
    with pytest.raises(ValidationError):
        TypeAdapter(AuditRequirement).validate_python(
            {
                "id": "r",
                "group": "g",
                "name": "n",
                "status": "not_met",
                "credits_required": 3,
                "credits_needed": 3,
                "options": ["CSE111"],
            }
        )


# --- Stub endpoints --------------------------------------------------------------

ENDPOINTS: list[tuple[str, str, dict[str, object] | None, Any]] = [
    ("POST", "/api/session", {"consent": True}, SessionResponse),
    ("POST", "/api/audit/sample", None, DegreeAudit),
    ("GET", "/api/requirements/remaining", None, list[AuditRequirement]),
    ("GET", "/api/constraints", None, ConstraintSet),
    ("GET", "/api/chat/history", None, ChatHistory),
    (
        "PUT",
        "/api/constraints",
        {"credit_min": 12, "credit_max": 15, "days_off": ["F"]},
        ConstraintSet,
    ),
    ("POST", "/api/schedules/build", {}, BuildSchedulesResponse),
    ("GET", "/api/professors", None, list[Professor]),
    ("GET", "/api/professors/p-hale", None, Professor),
    ("PUT", "/api/professors/p-hale/favorite", {"favorite": True}, FavoriteProfessor),
    (
        "POST",
        "/api/mentors/search",
        {"goal": "research", "tags": ["machine learning"]},
        list[MentorMatch],
    ),
    ("POST", "/api/mentors/p-hale/email-draft", {"goal": "research"}, EmailDraft),
]


@pytest.mark.parametrize(("method", "path", "body", "model"), ENDPOINTS)
def test_stub_endpoint_validates(
    method: str, path: str, body: dict[str, object] | None, model: Any
) -> None:
    response = client.request(method, path, json=body)
    assert response.status_code == 200, response.text
    TypeAdapter(model).validate_python(response.json())


def test_audit_upload_is_off_by_default() -> None:
    # The real upload (AI-04) sits behind FEATURE_AUDIT_UPLOAD; it is tested on
    # recorded replies in test_audit_no_pdf_kept.py.
    response = client.post(
        "/api/audit", files={"file": ("audit.pdf", b"%PDF-1.4 fake", "application/pdf")}
    )
    assert response.status_code == 404


def test_audit_put_echoes() -> None:
    audit = client.post("/api/audit/sample").json()
    response = client.put("/api/audit", json=audit)
    assert response.status_code == 200
    assert response.json() == audit


def test_chat_stub_streams_chat_events() -> None:
    with client.stream("POST", "/api/chat", json={"message": "No Fridays"}) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        lines = [line for line in response.iter_lines() if line.startswith("data: ")]
    events = [ChatEvent.model_validate_json(line.removeprefix("data: ")) for line in lines]
    assert events[-1].type == "done"


def test_delete_me_stub() -> None:
    assert client.delete("/api/me").status_code == 204


def test_request_log_stubs() -> None:
    assert "0 outbound requests" in client.get("/admin/request-log").text
    csv = client.get("/admin/request-log.csv")
    assert csv.headers["content-type"].startswith("text/csv")
    assert csv.text.startswith("id,at,method,url,status,cookie_sent,auth_sent")


def test_unknown_professor_404() -> None:
    assert client.get("/api/professors/nobody").status_code == 404


def test_schedules_end_with_advising_note() -> None:
    response = client.post("/api/schedules/build", json={})
    result = BuildSchedulesResponse.model_validate(response.json())
    assert len(result.schedules) == 3
    for schedule in result.schedules:
        assert schedule.advising_note == "Confirm with BYU-Idaho Academic Advising."


def test_openapi_lists_every_contract_model() -> None:
    schemas = client.get("/openapi.json").json()["components"]["schemas"]
    missing = [name for name in REQUIRED_MODELS if name not in schemas]
    assert not missing
