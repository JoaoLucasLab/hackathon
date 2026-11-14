"""AI-05: outreach email drafts. Under 180 words, names the class the student took
with that professor, mentions the grade only when asked, never sent.

Replays recorded Claude replies (no network, no live Claude call).
"""

from __future__ import annotations

import ast
import json
import tomllib
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api import fixture_data
from app.contracts import AuditCourse, CourseRecordStatus, MentorGoal
from app.llm import client as llm_client
from app.llm import mentor_text
from app.main import app

REPO = Path(__file__).resolve().parents[2]
RECORDINGS = Path(__file__).parent / "data" / "recordings" / "mentors"
api = TestClient(app)


class Recorded:
    def __init__(self, replies: list[str | None]) -> None:
        self.replies = list(replies)
        self.requests: list[dict[str, Any]] = []

    def __call__(self, params: dict[str, Any]) -> str | None:
        self.requests.append(params)
        return self.replies.pop(0)


def _prof(pid: str) -> Any:
    return fixture_data.professor_by_id()[pid]


def _courses() -> list[AuditCourse]:
    return fixture_data.audit().courses


def _reply(subject: str, body: str) -> str:
    return json.dumps({"subject": subject, "body": body})


# --- Which class the student took with the professor -----------------------------


@pytest.mark.parametrize(
    ("pid", "expected"),
    [
        ("p-hale", "CSE 111"),
        ("p-okafor", "WDD 130"),  # the finished class wins over WDD 131 in progress
        ("p-lindqvist", "CSE 210"),  # in progress only
        ("p-smith-rel", "REL 250"),
        ("p-smith-cse", None),  # same name, other department: never merged
        ("p-reyes", None),
    ],
)
def test_pick_class(pid: str, expected: str | None) -> None:
    taken = mentor_text.pick_class(_prof(pid), _courses())
    assert (taken.course_code if taken else None) == expected


def test_middle_initial_must_agree_when_both_show_one() -> None:
    row = AuditCourse(
        course_code="CSE 310",
        title="Applied Programming",
        credits=3,
        grade="A",
        term="Fall 2025",
        status=CourseRecordStatus.complete,
        instructor="Okafor, Ruth B.",
    )
    assert mentor_text.classes_with(_prof("p-okafor"), [row]) == []


# --- Template draft (no Claude) ------------------------------------------------------


@pytest.mark.parametrize("goal", list(MentorGoal))
@pytest.mark.parametrize("mention_grade", [False, True])
def test_template_draft_meets_the_rules(goal: MentorGoal, mention_grade: bool) -> None:
    draft = mentor_text.draft_email(
        _prof("p-hale"), goal, ["machine learning"], _courses(), mention_grade
    )
    assert draft.written_by == "template"
    assert mentor_text.word_count(draft.body) < 180
    assert draft.class_named == "CSE 111"
    assert "CSE 111" in draft.body
    assert ("B+" in draft.body) is mention_grade
    assert "[Your name]" in draft.body
    facts = mentor_text.email_facts(
        _prof("p-hale"),
        goal,
        ["machine learning"],
        mentor_text.pick_class(_prof("p-hale"), _courses()),
        mention_grade,
    )
    mentor_text.check_email(draft.subject, draft.body, facts)


def test_in_progress_class_never_mentions_a_grade() -> None:
    draft = mentor_text.draft_email(
        _prof("p-lindqvist"), MentorGoal.ta_job, [], _courses(), mention_grade=True
    )
    assert "CSE 210" in draft.body
    assert "taking" in draft.body
    assert "grade" not in draft.body.lower() and "earned" not in draft.body


def test_no_shared_class_names_no_course() -> None:
    draft = mentor_text.draft_email(
        _prof("p-reyes"), MentorGoal.research, ["statistics"], _courses(), mention_grade=True
    )
    assert draft.class_named is None
    assert mentor_text.course_codes_in(draft.body) == set()
    assert "statistics" in draft.body


def test_only_the_professors_own_tags_are_used() -> None:
    facts = mentor_text.email_facts(
        _prof("p-hale"), MentorGoal.research, ["machine learning", "church history"], None, False
    )
    assert facts["topics"] == ["machine learning"]


# --- Claude draft ---------------------------------------------------------------------


def test_recorded_claude_draft() -> None:
    rec = json.loads((RECORDINGS / "email-hale.json").read_text())
    caller = Recorded(rec["replies"])
    draft = mentor_text.draft_email(
        _prof("p-hale"), MentorGoal.research, ["machine learning"], _courses(), False, caller
    )
    assert draft.written_by == "claude"
    assert draft.class_named == "CSE 111"
    assert "CSE 111" in draft.body
    assert mentor_text.word_count(draft.body) < 180
    assert caller.requests[0]["model"] == llm_client.chat_model()


def test_grade_is_not_sent_unless_the_student_ticks_it() -> None:
    reply = _reply("Research", "Dear Professor Hale,\n\nI took CSE 111 with you.\n\n[Your name]")
    off, on = Recorded([reply]), Recorded([reply])
    mentor_text.draft_email(_prof("p-hale"), MentorGoal.research, [], _courses(), False, off)
    mentor_text.draft_email(_prof("p-hale"), MentorGoal.research, [], _courses(), True, on)
    sent_off = json.loads(off.requests[0]["messages"][0]["content"])
    sent_on = json.loads(on.requests[0]["messages"][0]["content"])
    assert "grade" not in sent_off["class_taken"]
    assert sent_on["class_taken"]["grade"] == "B+"


def test_no_personal_details_are_sent() -> None:
    reply = _reply("Research", "Dear Professor Hale,\n\nI took CSE 111 with you.\n\n[Your name]")
    caller = Recorded([reply])
    mentor_text.draft_email(_prof("p-hale"), MentorGoal.research, [], _courses(), True, caller)
    sent = json.loads(caller.requests[0]["messages"][0]["content"])
    assert set(sent) == {"goal", "professor", "topics", "class_taken", "sign_off"}
    assert set(sent["professor"]) == {"last_name", "title", "department"}


@pytest.mark.parametrize(
    ("body", "problem"),
    [
        ("Dear Professor Hale, I took CSE 111. " + "word " * 180, "words"),
        ("Dear Professor Hale, I took CSE 111 and CSE 212 with you.", "CSE 212"),
        ("Dear Professor Hale, I enjoyed your class.", "must name CSE 111"),
        ("Dear Professor Hale, I took CSE 111 and got an A.", "grade"),
    ],
)
def test_bad_drafts_are_rejected(body: str, problem: str) -> None:
    facts = mentor_text.email_facts(
        _prof("p-hale"),
        MentorGoal.research,
        [],
        mentor_text.pick_class(_prof("p-hale"), _courses()),
        False,
    )
    with pytest.raises(mentor_text.NotGroundedError, match=problem):
        mentor_text.check_email("Research", body, facts)


def test_two_bad_drafts_fall_back_to_the_template() -> None:
    bad = _reply("Research", "Dear Professor Hale, I took CSE 212 with you.")
    caller = Recorded([bad, bad])
    draft = mentor_text.draft_email(
        _prof("p-hale"), MentorGoal.research, [], _courses(), False, caller
    )
    assert len(caller.requests) == 2
    assert draft.written_by == "template"
    assert "CSE 212" not in draft.body


# --- Endpoint and "never sent" --------------------------------------------------------


def test_endpoint_returns_a_draft_only() -> None:
    response = api.post(
        "/api/mentors/p-hale/email-draft",
        json={"goal": "recommendation letter", "mention_grade": True, "tags": []},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["class_named"] == "CSE 111"
    assert "B+" in body["body"]
    assert set(body) == {"professor_id", "subject", "body", "class_named", "written_by"}
    assert api.post("/api/mentors/nobody/email-draft", json={"goal": "research"}).status_code == 404


MAIL_PACKAGES = {"sendgrid", "mailgun", "postmarker", "yagmail", "fastapi-mail", "aiosmtplib"}
MAIL_MODULES = {"smtplib", "aiosmtplib", "sendgrid", "yagmail", "fastapi_mail", "postmarker"}


def test_backend_has_no_mail_sending_dependency() -> None:
    project = tomllib.loads((REPO / "pyproject.toml").read_text())["project"]
    deps = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        deps += extra
    names = {
        d.split(">")[0].split("=")[0].split("<")[0].split("[")[0].strip().lower() for d in deps
    }
    assert not names & MAIL_PACKAGES

    imported: set[str] = set()
    for path in (REPO / "backend" / "app").rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                imported |= {a.name.split(".")[0] for a in node.names}
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
    assert not imported & MAIL_MODULES
