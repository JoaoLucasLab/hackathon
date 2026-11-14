"""Environment settings.

DATA-01 owns this file; ENG-01 created the first version. Every name here is the
same on Render and on the WSL backup host (.env.example, deploy/wsl/.env.example).
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
# Postgres. A plain postgresql:// URL (Neon, the compose files); app/db/engine.py picks
# the driver. Empty: students and sessions live in memory (local dev and tests only).
DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
# Signs the `sid` session cookie. Empty: a random key per process (sessions end on restart).
SESSION_SECRET = os.environ.get("SESSION_SECRET", "").strip()
# `none` on Render (frontend and API on different sites), `lax` on WSL (one origin).
COOKIE_SAMESITE = os.environ.get("COOKIE_SAMESITE", "lax").strip().lower() or "lax"
# Encrypts audit JSON and chat messages at rest (app/db/crypto.py). Any secret string
# (`openssl rand -base64 32`). Empty: a random key per process (local dev and tests only).
DATA_KEY = os.environ.get("DATA_KEY", "").strip()
# Exact frontend origin allowed by CORS (with cookies). Empty: no cross-origin calls.
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "").strip().rstrip("/")
# The default credit range, score weights and other school rules live in
# schools/byui/config.yaml (ENG-05), read through SchoolRules.


def _flag(name: str) -> bool:
    return os.environ.get(name, "false").strip().lower() == "true"


# AI-07 / AI-08: the chat asks questions before it builds, and shows one schedule at
# a time. Off in production until AI-08 passes its tests. Read at call time
# (`config.FEATURE_CONVERSATIONAL_PLANNER`) so tests can switch it.
FEATURE_CONVERSATIONAL_PLANNER = _flag("FEATURE_CONVERSATIONAL_PLANNER")
