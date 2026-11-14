"""Catalog prerequisite text -> `PrereqExpression` tree (ENG-04).

Structure is read in code. Text this parser cannot read raises `PrereqParseError`;
`llm/prereq_fallback.py` then asks Claude Haiku, and anything still unreadable is
stored as `unparsed` (a warning, never "no prerequisites").

Course Search's structured requisite rows already become trees in
`scripts/data_cleaner.py`, and DATA-04 stores that tree in `courses.prereq` next
to the site's "requisites_expression" in `courses.prereq_text`. `PrereqChecker`
uses the stored tree, so that text is never parsed here (its "[group] Course
Prerequisite: ..." form would go to the fallback). This parser is for plain
catalog-style text: the fixtures and courses that come without a tree.

What it reads:
- course codes (`CSE 111`, `CSE111`, `CSE 111-01`); a bare number after a course
  (`CSE 110 or 111`) keeps the previous subject,
- `and`, `or`, commas (`A, B, and C`) and parentheses for grouping. Mixing `and` and
  `or` at one level without parentheses is ambiguous and is not guessed,
- minimum grades: `MATH 112 with a C or better`, `MATH 215 (C or better)`,
- `(may be taken concurrently)` -> `concurrent_ok`,
- `(last offered 2023)` is a note about the course and is dropped (the course
  still counts when it is on the student's record),
- conditions the app cannot verify (standing, consent, placement and test scores,
  PathwayConnect, ...) -> `condition` nodes.

The result is always an `all` node at the top: `CSE 210` -> ALL[CSE 210] and empty
text -> ALL[] ("the catalog lists none").
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.contracts import (
    PrereqAll,
    PrereqAny,
    PrereqCondition,
    PrereqCourse,
    PrereqExpression,
    PrereqUnparsed,
)


class PrereqParseError(ValueError):
    """The text has a part the code parser cannot read."""


_GRADE = r"([A-D][+-]?)"
_GRADE_WORDS = r"(?:with\s+)?(?:an?\s+)?(?:(?:minimum\s+)?grade\s+of\s+)?"
_MIN = r" ⟨min:\1⟩"
_REWRITES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"^\s*pre-?requisites?\s*:\s*", re.I), ""),
    (re.compile(r"\s*\(\s*last\s+offered[^)]*\)", re.I), ""),
    (re.compile(rf"\s*\(\s*{_GRADE_WORDS}{_GRADE}\s+or\s+(?:better|higher)\s*\)", re.I), _MIN),
    (re.compile(rf",?\s+{_GRADE_WORDS}{_GRADE}\s+or\s+(?:better|higher)\b", re.I), _MIN),
    (re.compile(rf"\s*\(\s*minimum\s+grade\s*(?:of\s*)?:?\s*{_GRADE}\s*\)", re.I), _MIN),
    (
        re.compile(r"\s*\(\s*(?:may|can)\s+be\s+taken\s+concurrently\s*\)", re.I),
        " ⟨concurrent⟩",
    ),
    (
        re.compile(r",?\s+(?:which\s+)?(?:may|can)\s+be\s+taken\s+concurrently\b", re.I),
        " ⟨concurrent⟩",
    ),
]

_TOKEN = re.compile(r"(\()|(\))|(⟨[^⟩]*⟩)|(,)|\b(and|or)\b", re.I)
_COURSE = re.compile(r"([A-Z]{2,5})\s*(\d{3}[A-Z]?)(?:-\d+)?")
_BARE_NUMBER = re.compile(r"\d{3}[A-Z]?")
_CONDITION_WORDS = re.compile(
    r"standing|consent|permission|approval|placement|score|\btest\b|\bexam\b|pathway"
    r"|admission|admitted|\bmajor\b|instructor|department|\bACT\b|\bSAT\b|ALEKS|\bLUC\b",
    re.I,
)
_NO_PREREQS = re.compile(r"^(?:none|n/?a|no prerequisites?)\.?$", re.I)


@dataclass
class _Tok:
    kind: str  # "(" ")" "attr" "," "and" "or" "atom"
    text: str


def _normalize(text: str) -> str:
    out = " ".join(text.split()).strip().rstrip(".;")
    for pattern, repl in _REWRITES:
        out = pattern.sub(repl, out)
    return out.strip()


def _tokenize(text: str) -> list[_Tok]:
    tokens: list[_Tok] = []
    pos = 0

    def atom(chunk: str) -> None:
        chunk = chunk.strip()
        if chunk:
            tokens.append(_Tok("atom", chunk))

    for m in _TOKEN.finditer(text):
        atom(text[pos : m.start()])
        pos = m.end()
        if m.group(1):
            tokens.append(_Tok("(", "("))
        elif m.group(2):
            tokens.append(_Tok(")", ")"))
        elif m.group(3):
            tokens.append(_Tok("attr", m.group(3)[1:-1]))
        elif m.group(4):
            tokens.append(_Tok(",", ","))
        else:
            tokens.append(_Tok(m.group(5).lower(), m.group(5)))
    atom(text[pos:])
    return tokens


class _Parser:
    def __init__(self, tokens: list[_Tok]) -> None:
        self.tokens = tokens
        self.i = 0
        self.last_subject: str | None = None

    def peek(self) -> _Tok | None:
        return self.tokens[self.i] if self.i < len(self.tokens) else None

    def take(self) -> _Tok:
        tok = self.peek()
        if tok is None:
            raise PrereqParseError("the text ends too early")
        self.i += 1
        return tok

    def expr(self) -> PrereqExpression:
        items = [self.term()]
        connectors: list[str] = []
        while (tok := self.peek()) is not None and tok.kind in (",", "and", "or"):
            self.take()
            kind = tok.kind
            if kind == "," and (nxt := self.peek()) is not None and nxt.kind in ("and", "or"):
                kind = self.take().kind  # "A, B, and C"
            connectors.append(kind)
            items.append(self.term())
        # A bare comma takes the word used later in the same list ("A, B or C").
        resolved: list[str] = []
        for n, c in enumerate(connectors):
            if c == ",":
                c = next((w for w in connectors[n + 1 :] if w != ","), "and")
            resolved.append(c)
        kinds = set(resolved)
        if len(kinds) > 1:
            raise PrereqParseError("mixes 'and' and 'or' without parentheses")
        if not kinds:
            return items[0]
        return _combine("all" if kinds == {"and"} else "any", items)

    def term(self) -> PrereqExpression:
        tok = self.take()
        if tok.kind == "(":
            node = self.expr()
            if self.take().kind != ")":
                raise PrereqParseError("a parenthesis is not closed")
        elif tok.kind == "atom":
            node = self.atom(tok.text)
        else:
            raise PrereqParseError(f"unexpected {tok.text!r}")
        while (nxt := self.peek()) is not None and nxt.kind == "attr":
            node = _apply_attr(node, self.take().text)
        return node

    def atom(self, text: str) -> PrereqExpression:
        m = _COURSE.fullmatch(text.upper())
        if m:
            self.last_subject = m.group(1)
            return PrereqCourse(course_code=f"{m.group(1)} {m.group(2)}")
        if _BARE_NUMBER.fullmatch(text.upper()) and self.last_subject:
            return PrereqCourse(course_code=f"{self.last_subject} {text.upper()}")
        if _CONDITION_WORDS.search(text):
            return PrereqCondition(text=text)
        raise PrereqParseError(f"cannot read {text!r}")


def _apply_attr(node: PrereqExpression, attr: str) -> PrereqExpression:
    if isinstance(node, PrereqCourse):
        if attr == "concurrent":
            return node.model_copy(update={"concurrent_ok": True})
        if attr.startswith("min:"):
            return node.model_copy(update={"min_grade": attr[4:].upper()})
    if isinstance(node, PrereqAll | PrereqAny):
        return node.model_copy(update={"items": [_apply_attr(i, attr) for i in node.items]})
    raise PrereqParseError(f"'{attr}' does not follow a course")


def _combine(kind: str, items: list[PrereqExpression]) -> PrereqExpression:
    """Flattens nested nodes of the same kind and drops exact duplicates."""
    cls = PrereqAll if kind == "all" else PrereqAny
    flat: list[PrereqExpression] = []
    for item in items:
        for sub in item.items if isinstance(item, cls) else [item]:
            if sub not in flat:
                flat.append(sub)
    return cls(items=flat)


def parse_prereq_text(text: str | None) -> PrereqAll:
    """Parse catalog text. Raises `PrereqParseError` when any part cannot be read."""
    if text is None or not text.strip() or _NO_PREREQS.match(text.strip()):
        return PrereqAll(items=[])
    parser = _Parser(_tokenize(_normalize(text)))
    if parser.peek() is None:
        raise PrereqParseError("nothing to read")
    node = parser.expr()
    if parser.peek() is not None:
        raise PrereqParseError(f"unexpected {parser.peek().text!r}")  # type: ignore[union-attr]
    return node if isinstance(node, PrereqAll) else PrereqAll(items=[node])


def parse_or_unparsed(text: str | None) -> PrereqExpression:
    """Code parser only: text it cannot read becomes an `unparsed` node."""
    try:
        return parse_prereq_text(text)
    except PrereqParseError:
        return PrereqUnparsed(text=text or "")
