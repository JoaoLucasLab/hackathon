"""Degree audit PDF to `DegreeAudit` with Claude (AI-04).

School-agnostic. A school's `DegreeAuditParser` (for BYU-Idaho:
`schools/byui/audit_parser.py`) calls `parse_audit_pdf` with its own `prepare`
hook, which normalizes the school's course codes before validation.

Privacy and truthfulness rules this module enforces:

- The PDF bytes are sent to Claude exactly once and never written to disk, the
  database or a log. The retry after a validation error sends only the JSON Claude
  returned and the error, not the PDF again.
- The result has no student name and no ID number: the schema has no field for them,
  `extra="forbid"` rejects any extra field, and a reply that contains something that
  looks like a student ID number is rejected.
- Requirement ids are rebuilt from the group name and position, so they are stable
  and unique whatever Claude wrote.
- Validation flags (unknown course, credits that do not add up, invalid status) are
  added by the validation step, not by Claude: Claude's `validation_flags` is
  always empty.

If the reply fails validation twice, or Claude declines, `AuditParseError` is
raised and the screen shows "We couldn't read this audit".
"""

from __future__ import annotations

import base64
import logging
import re
from collections.abc import Callable
from typing import Any

import anthropic
from anthropic import transform_schema
from pydantic import BaseModel, ConfigDict, ValidationError

from app.contracts import DegreeAudit
from app.llm import client

log = logging.getLogger(__name__)

MAX_TOKENS = 16000
# Extraction, not reasoning: low effort keeps the confirm screen under 60 seconds.
AUDIT_EFFORT = "low"
# One audit can take longer than a chat turn; still well under the 60 s target
# most of the time, and a hard stop if Claude is slow.
AUDIT_TIMEOUT_S = 90.0

# A BYU-Idaho I-Number is 9 digits; also catch US SSN-style numbers. Course
# numbers (3 digits), credits and dates never match.
ID_NUMBER = re.compile(r"(?<!\d)(?:\d{9}|\d{3}-\d{2}-\d{4}|\d{3}-\d{3}-\d{3})(?!\d)")

USER_TEXT = "Extract this degree audit as JSON, following the rules in the system prompt."


class AuditParseError(RuntimeError):
    """The audit could not be read. The message is safe to show the student."""


class _Reply(BaseModel):
    """What Claude returns: the audit, or `readable=False` for a document that is
    not a degree audit."""

    model_config = ConfigDict(extra="forbid")

    readable: bool
    audit: dict[str, Any] | None


def output_schema() -> dict[str, Any]:
    """JSON schema for structured output. Built from the `DegreeAudit` contract so
    the two never drift; `validation_flags` is left out (the app adds them)."""
    audit = DegreeAudit.model_json_schema()
    audit["properties"].pop("validation_flags", None)
    if "validation_flags" in audit.get("required", []):
        audit["required"].remove("validation_flags")
    audit["$defs"].pop("ValidationFlag", None)
    defs = audit.pop("$defs", {})
    schema = {
        "type": "object",
        "properties": {
            "readable": {"type": "boolean"},
            "audit": {"anyOf": [{"$ref": "#/$defs/DegreeAudit"}, {"type": "null"}]},
        },
        "required": ["readable", "audit"],
        "additionalProperties": False,
        "$defs": {**defs, "DegreeAudit": audit},
    }
    return transform_schema(schema)


# A Caller takes the request parameters and returns the reply's JSON text, or None
# when Claude declined. Tests pass a recorded one; nothing here hits the API.
Caller = Callable[[dict[str, Any]], str | None]
# School hook: normalizes the raw audit dict (course codes, ...) before validation.
Prepare = Callable[[dict[str, Any]], dict[str, Any]]


def first_params(pdf: bytes) -> dict[str, Any]:
    """The one request that carries the PDF."""
    document = {
        "type": "document",
        "source": {
            "type": "base64",
            "media_type": "application/pdf",
            "data": base64.standard_b64encode(pdf).decode("ascii"),
        },
    }
    return _params([{"role": "user", "content": [document, {"type": "text", "text": USER_TEXT}]}])


def retry_params(previous: str, error: str) -> dict[str, Any]:
    """The retry: only the JSON Claude returned and why it was rejected. No PDF."""
    text = (
        "You extracted the JSON below from a degree audit PDF. The app rejected it:\n"
        f"{error}\n\n"
        "Return the corrected JSON. Fix only what the error names. Do not add any "
        "course, grade, credit or requirement that is not already in the JSON.\n\n"
        f"{previous}"
    )
    return _params([{"role": "user", "content": text}])


def _params(messages: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "model": client.chat_model(),
        "max_tokens": MAX_TOKENS,
        "system": client.cached_system("audit"),
        "messages": messages,
        "output_config": {
            "effort": AUDIT_EFFORT,
            "format": {"type": "json_schema", "schema": output_schema()},
        },
        **client.chat_fallback_options(),
    }


def claude_caller(params: dict[str, Any]) -> str | None:
    """The real Caller. Returns None on a refusal or a cut-off reply."""
    message = (
        client.get_client()
        .with_options(timeout=AUDIT_TIMEOUT_S)
        .beta.messages.create(**params)
    )
    if message.stop_reason in ("refusal", "max_tokens"):
        log.warning("audit: no answer, stop_reason=%s", message.stop_reason)
        return None
    return next((b.text for b in message.content if b.type == "text"), None)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "requirement"


def _renumber_requirements(audit: dict[str, Any]) -> None:
    counts: dict[str, int] = {}
    for req in audit.get("requirements") or []:
        if isinstance(req, dict):
            group = _slug(str(req.get("group", "")))
            counts[group] = counts.get(group, 0) + 1
            req["id"] = f"{group}-{counts[group]}"


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings(v)]
    return []


def check_no_id_number(audit: dict[str, Any]) -> None:
    if any(ID_NUMBER.search(s) for s in _strings(audit)):
        raise ValueError(
            "A text field contains a student ID number. Remove every ID number; "
            "the JSON must not identify the student."
        )


def to_audit(text: str, prepare: Prepare) -> DegreeAudit | None:
    """Validate one reply. None means Claude said the document is not readable.
    Raises ValidationError or ValueError for a reply worth retrying."""
    reply = _Reply.model_validate_json(text)
    if not reply.readable or reply.audit is None:
        return None
    raw = prepare(dict(reply.audit))
    raw["validation_flags"] = []
    _renumber_requirements(raw)
    check_no_id_number(raw)
    return DegreeAudit.model_validate(raw)


UNREADABLE = "We couldn't read this audit."


def parse_audit_pdf(
    pdf: bytes,
    prepare: Prepare = lambda raw: raw,
    caller: Caller = claude_caller,
) -> DegreeAudit:
    """One parse: the PDF goes to Claude once; one retry on invalid JSON."""
    params = first_params(pdf)
    del pdf  # nothing below needs the bytes
    for attempt in range(2):
        try:
            text = caller(params)
        except client.ClaudeNotConfiguredError:
            log.warning("audit: ANTHROPIC_API_KEY is not set")
            raise AuditParseError(UNREADABLE) from None
        except anthropic.APIError as exc:
            # Only the error type and status: never the request body (it holds the PDF).
            log.warning(
                "audit: Claude API error %s (status %s)",
                type(exc).__name__,
                getattr(exc, "status_code", None),
            )
            raise AuditParseError(UNREADABLE) from None
        if text is None:
            raise AuditParseError(UNREADABLE)
        try:
            audit = to_audit(text, prepare)
        except (ValidationError, ValueError) as exc:
            # The exception text can quote values from the audit: log only its type.
            log.info("audit: reply rejected on attempt %d: %s", attempt + 1, type(exc).__name__)
            params = retry_params(text, _short_error(exc))
            continue
        if audit is None:
            raise AuditParseError(UNREADABLE)
        return audit
    log.warning("audit: two replies failed validation")
    raise AuditParseError(UNREADABLE)


def _short_error(exc: Exception) -> str:
    if isinstance(exc, ValidationError):
        return "\n".join(
            f"- {'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()[:20]
        )
    return f"- {exc}"


__all__ = [
    "AuditParseError",
    "Caller",
    "Prepare",
    "UNREADABLE",
    "output_schema",
    "parse_audit_pdf",
]
