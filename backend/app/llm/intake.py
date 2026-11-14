"""Conversational intake before the first schedule (AI-07).

With `FEATURE_CONVERSATIONAL_PLANNER` on, the assistant asks questions first and
builds a schedule only when the student agrees. The system prompt tells the model
that; this module is the backend half, so a model that skips ahead still cannot
build:

- `IntakeState` is what the session knows about the readiness checklist.
- `check_build` is the gate the `build_schedules` tool runs before the solver.
- `ChoiceFilter` takes the model's `<<choices: A | B>>` line out of the streamed
  text; the chat loop sends the options to the frontend as quick replies.

Nothing here knows about BYU-Idaho: the track comes from the audit contract and
the default credit range from `SchoolRules` (through the caller).
"""

from __future__ import annotations

from dataclasses import dataclass

from app.contracts import ConstraintSet, Track

# After this many rounds of questions the app tells the model to offer to build
# with defaults for the optional items.
MAX_QUESTION_ROUNDS = 4

MAX_QUICK_REPLIES = 4
MAX_QUICK_REPLY_CHARS = 40

CHOICES_OPEN = "<<choices:"
CHOICES_CLOSE = ">>"

OFFER_DEFAULTS_NOTE = (
    "[App note, not from the student: you have asked questions for "
    f"{MAX_QUESTION_ROUNDS} rounds. Do not ask about optional items again. If the track "
    "and credit load are known, offer to build now with defaults for anything still "
    "open. Otherwise ask only for the missing required item.]"
)


class NotReadyError(RuntimeError):
    """`build_schedules` was called too early. The message tells the model what to do."""


@dataclass
class IntakeState:
    """What one session knows about the readiness checklist. No personal details."""

    student_turns: int = 0
    question_rounds: int = 0
    # The track the student stated, when the audit does not show one.
    stated_track: Track | None = None
    credit_load_known: bool = False
    agreed_to_build: bool = False
    built: bool = False

    def start_turn(self) -> None:
        self.student_turns += 1

    def end_turn(self, built_this_turn: bool) -> None:
        """A turn that ends before the first schedule is a round of questions."""
        if not self.built and not built_this_turn:
            self.question_rounds += 1

    def should_offer_defaults(self) -> bool:
        return not self.built and self.question_rounds >= MAX_QUESTION_ROUNDS


def check_build(
    state: IntakeState,
    *,
    audit_track: Track | None,
    constraints: ConstraintSet,
    stated_track: Track | None,
    use_default_credits: bool,
    student_agreed: bool,
) -> Track | None:
    """Gate for `build_schedules`. Records what the arguments say, checks them
    against the audit, and raises NotReadyError naming what is missing.

    Returns the track the student stated when the audit has none (else None).
    """
    if audit_track is not None:
        if stated_track is not None and stated_track != audit_track:
            raise NotReadyError(
                f"not ready: the degree audit says the track is {audit_track.value}. "
                "Do not change it. Send track as null."
            )
    elif stated_track is not None:
        state.stated_track = stated_track

    if constraints.credit_min is not None or constraints.credit_max is not None:
        state.credit_load_known = True
    elif use_default_credits:
        state.credit_load_known = True

    missing: list[str] = []
    if audit_track is None and state.stated_track is None:
        missing.append("track")
    if not state.credit_load_known:
        missing.append("credit load")
    if missing:
        raise NotReadyError(f"not ready: ask the student for {' and '.join(missing)}")

    if state.built:
        # After the first schedule the student is giving feedback: rebuilds are allowed.
        return state.stated_track

    if state.student_turns <= 1:
        raise NotReadyError(
            "not ready: this is the student's first message. Restate their preferences "
            'in a short list and ask "Should I build a schedule with these?"'
        )
    if not student_agreed:
        raise NotReadyError(
            "not ready: the student has not agreed to build yet. Restate their "
            'preferences in a short list and ask "Should I build a schedule with these?"'
        )
    state.agreed_to_build = True
    return state.stated_track


def mark_built(state: IntakeState) -> None:
    state.built = True


# --- Quick replies -------------------------------------------------------------------


def parse_choices(body: str) -> list[str]:
    """`A | B | C` -> ["A", "B", "C"], trimmed, de-duplicated, bounded."""
    options: list[str] = []
    for raw in body.split("|"):
        option = " ".join(raw.split())
        if option and len(option) <= MAX_QUICK_REPLY_CHARS and option not in options:
            options.append(option)
    return options[:MAX_QUICK_REPLIES]


class ChoiceFilter:
    """Removes a trailing `<<choices: A | B>>` line from streamed text.

    `feed` returns the text that is safe to show now. Text that could be the start
    of the marker is held back until the next delta settles it. `finish` returns
    any held-back text that turned out not to be a marker.
    """

    def __init__(self) -> None:
        self._held = ""
        self._in_marker = False
        self._marker = ""
        self.choices: list[str] = []

    def feed(self, delta: str) -> str:
        if self._in_marker:
            self._marker += delta
            self._close_marker()
            return ""
        text = self._held + delta
        start = text.find(CHOICES_OPEN)
        if start != -1:
            self._held = ""
            self._in_marker = True
            self._marker = text[start + len(CHOICES_OPEN) :]
            self._close_marker()
            return text[:start].rstrip()
        # Hold back a tail that could still grow into the marker.
        keep = 0
        for size in range(min(len(CHOICES_OPEN) - 1, len(text)), 0, -1):
            if CHOICES_OPEN.startswith(text[-size:]):
                keep = size
                break
        # Whitespace right before a possible marker is held too, so the shown text
        # does not end with a dangling newline.
        shown = text[: len(text) - keep] if keep else text
        stripped = shown.rstrip()
        self._held = text[len(stripped) :]
        return stripped

    def _close_marker(self) -> None:
        end = self._marker.find(CHOICES_CLOSE)
        if end != -1:
            self.choices = parse_choices(self._marker[:end])
            self._marker = ""

    def finish(self) -> str:
        """Text held back at the end of the message (trailing whitespace is dropped)."""
        if self._in_marker:
            return ""
        tail, self._held = self._held.rstrip(), ""
        return tail
