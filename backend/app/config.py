"""Environment settings.

Minimal version created by ENG-01 because the DATA-01 skeleton was not merged yet.
DATA-01 owns this file and may replace it; keep the names below.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

FIXTURES_DIR = Path(os.environ.get("FIXTURES_DIR", REPO_ROOT / "fixtures"))
CLAUDE_MODEL_CHAT = os.environ.get("CLAUDE_MODEL_CHAT", "claude-sonnet-5-5")
CLAUDE_MODEL_BULK = os.environ.get("CLAUDE_MODEL_BULK", "claude-haiku-5-5")
# Empty by default: zero outbound requests to BYU-Idaho. Do not change the default.
LIVE_SOURCES = [s for s in os.environ.get("LIVE_SOURCES", "").split(",") if s.strip()]
# ENG-03 scheduler. Each CP-SAT solve stops here and returns the best found.
SOLVER_TIME_LIMIT_S = float(os.environ.get("SOLVER_TIME_LIMIT_S", "3"))
# The default credit range, score weights and other school rules live in
# schools/byui/config.yaml (ENG-05), read through SchoolRules.
