"""Rate limits (DATA-06): chat 20 messages per 5 minutes, audit upload 5 per hour.

Used as route dependencies: `dependencies=[Depends(limits.CHAT)]`. Over the limit
the request gets 429 with a message the student can read and a `Retry-After` header.

Counted in memory, per process: each host runs the backend as one process, and the
project has no Redis. The key is the signed `sid` cookie; a request without one (or
with a cookie we did not sign) is counted by client address, so making up cookies
does not reset the count. Behind Render or nginx the address comes from
X-Forwarded-For (uvicorn --proxy-headers, backend/Dockerfile).
"""

from __future__ import annotations

import math
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from app.api import session as session_api

# Above this many keys, keys with no recent request are dropped.
_PRUNE_AT = 10_000


class RateLimit:
    def __init__(self, max_requests: int, window_s: float, message: str) -> None:
        self.max_requests = max_requests
        self.window_s = window_s
        self.message = message
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def __call__(self, request: Request) -> None:
        key = self.key(request)
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > _PRUNE_AT:
                self._prune(now)
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - self.window_s:
                hits.popleft()
            if len(hits) >= self.max_requests:
                retry_after = math.ceil(hits[0] + self.window_s - now)
                raise HTTPException(
                    429, self.message, headers={"Retry-After": str(max(retry_after, 1))}
                )
            hits.append(now)

    @staticmethod
    def key(request: Request) -> str:
        cookie = request.cookies.get(session_api.COOKIE)
        if session_api.unsign(cookie) is not None:
            return f"sid:{cookie}"
        return f"ip:{request.client.host if request.client else 'unknown'}"

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_s
        for key in [k for k, hits in self._hits.items() if not hits or hits[-1] <= cutoff]:
            del self._hits[key]

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


CHAT = RateLimit(
    20,
    5 * 60,
    "You've sent 20 messages in the last 5 minutes. Wait a few minutes, then try again.",
)
UPLOAD = RateLimit(
    5,
    60 * 60,
    "You've uploaded 5 files in the last hour. Wait a while, then try again.",
)
