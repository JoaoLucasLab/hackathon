"""`GET /health` (DATA-01): the app is up and can reach its database.

Not in the OpenAPI schema, so frontend/src/api/types.ts does not change.
"""

from fastapi import APIRouter, Response

from app.db import engine

router = APIRouter(tags=["health"])


@router.get("/health", include_in_schema=False)
def health(response: Response) -> dict[str, str]:
    db = engine.ping()  # "ok", "not_configured" or "error"
    if db == "error":
        response.status_code = 503
    return {"status": "error" if db == "error" else "ok", "db": db}
