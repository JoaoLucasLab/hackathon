"""FastAPI app.

Minimal version created by ENG-01 because the DATA-01 skeleton was not merged yet.
DATA-01 owns this file (health check, session cookie, CORS) and may extend it.
This is the one place allowed to wire `schools/byui` in, through `register_school`.
"""

from typing import Any

from fastapi import FastAPI
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app import contracts
from app.api import routers
from app.contracts import ChatEvent
from app.schools.base import School, register_school
from app.schools.byui.audit_parser import ByuiAuditParser

# AI-04: the audit parser is the only piece of schools/byui wired in so far.
register_school(School(university_id="byui", name="BYU-Idaho", audit_parser=ByuiAuditParser()))

app = FastAPI(title="Course planner API", version="0.1.0")

for router in routers:
    app.include_router(router)


def _openapi() -> dict[str, Any]:
    """Standard schema, plus every contract model, so the generated TypeScript
    types include models no endpoint returns yet (Course, Term, TopicTags, ...)."""
    if app.openapi_schema:
        return app.openapi_schema
    schema = FastAPI.openapi(app)
    models: list[type[BaseModel]] = [*contracts.REQUIRED_MODELS.values(), ChatEvent]
    _, extra = models_json_schema(
        [(m, "serialization") for m in models], ref_template="#/components/schemas/{model}"
    )
    components = schema.setdefault("components", {}).setdefault("schemas", {})
    for name, definition in extra.get("$defs", {}).items():
        components.setdefault(name, definition)
    app.openapi_schema = schema
    return schema


app.openapi = _openapi  # type: ignore[method-assign]
