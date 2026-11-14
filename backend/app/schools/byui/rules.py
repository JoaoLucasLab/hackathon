"""BYU-Idaho school rules (ENG-05). Every value comes from `config.yaml`.

- Track: a campus student has a two-semester track. In an off-track semester only
  online sections are allowed. Online students (track `online`) take online
  sections only. An unknown track (None) filters nothing here: the chat asks the
  student for it.
- Religion: at most one religion course at registration.
- Waitlist: at most 12 waitlisted credits.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

import yaml

from app.contracts import (
    ConstraintSet,
    Course,
    DeliveryMethod,
    Excluded,
    ExclusionReason,
    Section,
    Student,
    Term,
)
from app.schools.base import SchoolRules
from app.schools.byui.rmp_link import rmp_link

CONFIG_PATH = Path(__file__).with_name("config.yaml")

ALL_DELIVERY = frozenset(DeliveryMethod)
ONLINE_ONLY = frozenset({DeliveryMethod.online})


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} must hold a mapping")
    return data


class ByuiRules(SchoolRules):
    def __init__(
        self, config: Mapping[str, Any] | None = None, courses: Iterable[Course] = ()
    ) -> None:
        self.config: Mapping[str, Any] = load_config() if config is None else config
        religion = self.config["religion"]
        self._religion_subjects = {str(s) for s in religion["subjects"]}
        # The catalog flag catches religion courses outside the usual subjects.
        self._religion_courses = {c.code for c in courses if c.is_religion}

    @classmethod
    def from_file(cls, path: Path, courses: Iterable[Course] = ()) -> ByuiRules:
        return cls(load_config(path), courses)

    # --- credits ----------------------------------------------------------------

    def default_credit_range(self) -> tuple[float, float]:
        return float(self.config["credit_default_min"]), float(self.config["credit_default_max"])

    def max_credit_limit(self) -> float:
        return float(self.config["credit_max_limit"])

    # --- track ------------------------------------------------------------------

    def season(self, term_code: str) -> str | None:
        """`2027;WI` and `2027;WI;W1` -> `winter`."""
        parts = term_code.split(";")
        if len(parts) < 2:
            return None
        seasons: Mapping[str, str] = self.config["term_seasons"]
        return seasons.get(parts[1])

    def _allowed(self, student: Student, term_code: str) -> frozenset[DeliveryMethod]:
        if student.track is None:
            return ALL_DELIVERY  # unknown: the chat asks; nothing is filtered here
        tracks: Mapping[str, list[str]] = self.config["tracks"]
        on_track = tracks.get(student.track.value, [])
        return ALL_DELIVERY if self.season(term_code) in on_track else ONLINE_ONLY

    def allowed_delivery(self, student: Student, term: Term) -> set[DeliveryMethod]:
        return set(self._allowed(student, term.code))

    def exclusion(
        self, section: Section, student: Student, constraints: ConstraintSet
    ) -> Excluded | None:
        allowed = self._allowed(student, section.term_code)
        if section.delivery_method in allowed:
            return None
        track = student.track.value if student.track else "unknown"
        return Excluded(
            section_id=section.id,
            reason=ExclusionReason.track,
            detail=f"track {track}: only online sections this semester",
        )

    # --- religion ---------------------------------------------------------------

    def is_religion_course(self, course_code: str) -> bool:
        return (
            course_code.split()[0] in self._religion_subjects
            or course_code in self._religion_courses
        )

    def max_religion_courses_at_registration(self) -> int:
        return int(self.config["religion"]["max_at_registration"])

    def religion_note(self) -> str:
        return str(self.config["religion"]["note"])

    # --- waitlist, scoring, relaxation, audit -------------------------------------

    def max_waitlisted_credits(self) -> float:
        return float(self.config["waitlist"]["max_credits"])

    def scoring_weights(self) -> Mapping[str, float]:
        return {str(k): float(v) for k, v in self.config["weights"].items()}

    def relaxation_order(self) -> list[str]:
        return [str(name) for name in self.config["relaxation_order"]]

    def audit_max_age_days(self) -> int:
        return int(self.config["audit_max_age_days"])

    # --- mentors (ENG-06) ---------------------------------------------------------

    def mentor_weights(self, goal: str) -> Mapping[str, float]:
        by_goal: Mapping[str, Mapping[str, Any]] = self.config["mentors"]["weights"]
        return {str(k): float(v) for k, v in by_goal[goal].items()}

    def mentor_min_grade(self) -> str:
        return str(self.config["mentors"]["min_grade"])

    def grade_scale(self) -> list[str]:
        return [str(g) for g in self.config["mentors"]["grade_scale"]]

    def mentor_max_results(self) -> int:
        return int(self.config["mentors"]["max_results"])

    # --- professors (DATA-05) -----------------------------------------------------

    def rmp_link(self, first_name: str, last_name: str) -> str:
        return rmp_link(first_name, last_name, str(self.config.get("rmp_school_id") or ""))
