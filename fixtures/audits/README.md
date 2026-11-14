# Golden degree audits (AI-04)

Each folder is one golden case for `backend/tests/test_audit_golden.py`:

- `recorded_reply.json`: Claude's structured reply for that audit (`{"readable", "audit"}`).
- `expected.json`: the hand-checked `DegreeAudit` the app must produce from it (course
  codes normalized, requirement ids rebuilt, validation flags computed with the audit's
  own date as "today").

No PDF is kept here, and none is needed: the tests replay the recorded reply.

**The three current cases are synthetic** (made up for the tests, no real student):
two majors (`cs-major`, `software-engineering-minor`, the second with no track shown)
and one transfer student (`transfer-student`). Replace them with replies recorded from
real audits only after removing every name, ID number and other personal detail, and
re-check `expected.json` by hand against the PDF. Never commit the PDFs themselves.

`fake-id-number.json` (DATA-06, `backend/tests/test_crypto.py`) is the sample audit
with two **made-up** student ID numbers in its text, to prove the store removes them
before saving.
