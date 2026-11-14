"""FastAPI app.

DATA-01 owns this file (health check, session cookie, CORS); ENG-01 created it.
This is the one place allowed to wire `schools/byui` in, through `register_school`.
"""

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pydantic.json_schema import models_json_schema

from app import config, contracts
from app.api import catalog_data, routers
from app.contracts import ChatEvent
from app.schools.base import School, register_school
from app.schools.byui.audit_parser import ByuiAuditParser
from app.schools.byui.rules import ByuiRules


def _register_schools() -> None:
    # Religion courses: subjects from config.yaml plus the catalog's `is_religion` flag.
    rules = ByuiRules(courses=catalog_data.courses())
    register_school(
        School(
            university_id=rules.config["university_id"],
            name="BYU-Idaho",
            rules=rules,  # ENG-05
            audit_parser=ByuiAuditParser(),  # AI-04
        )
    )


_register_schools()

def create_app() -> FastAPI:
    """The app, configured from the environment (app/config.py). Tests build their
    own with other settings, such as FRONTEND_ORIGIN (test_cors.py)."""
    app = FastAPI(title="Course planner API", version="0.1.0")

    # Render: the frontend is on another origin and sends the `sid` cookie with every
    # call. WSL and local dev are one origin, where CORS does not apply. Only
    # FRONTEND_ORIGIN: any other origin gets no CORS header.
    if config.FRONTEND_ORIGIN:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[config.FRONTEND_ORIGIN],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

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
    return app


app = create_app()
