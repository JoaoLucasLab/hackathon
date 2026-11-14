"""DATA-06: CORS allows only FRONTEND_ORIGIN. A request from another origin gets no
CORS header. Without FRONTEND_ORIGIN (WSL, local dev: one origin) there is none at all."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import config
from app.main import create_app

FRONTEND = "https://planner-web.example"
OTHER = "https://evil.example"


def _app(monkeypatch: pytest.MonkeyPatch, origin: str) -> FastAPI:
    monkeypatch.setattr(config, "FRONTEND_ORIGIN", origin)
    return create_app()


def test_the_frontend_origin_is_allowed_with_cookies(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(_app(monkeypatch, FRONTEND))
    res = client.get("/health", headers={"Origin": FRONTEND})
    assert res.headers["access-control-allow-origin"] == FRONTEND
    assert res.headers["access-control-allow-credentials"] == "true"
    pre = client.options(
        "/api/chat",
        headers={"Origin": FRONTEND, "Access-Control-Request-Method": "POST"},
    )
    assert pre.status_code == 200
    assert pre.headers["access-control-allow-origin"] == FRONTEND


def test_another_origin_gets_no_cors_header(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(_app(monkeypatch, FRONTEND))
    res = client.get("/health", headers={"Origin": OTHER})
    assert "access-control-allow-origin" not in res.headers
    pre = client.options(
        "/api/chat",
        headers={"Origin": OTHER, "Access-Control-Request-Method": "POST"},
    )
    assert pre.status_code == 400
    assert "access-control-allow-origin" not in pre.headers


def test_no_frontend_origin_means_no_cors(monkeypatch: pytest.MonkeyPatch) -> None:
    client = TestClient(_app(monkeypatch, ""))
    for origin in (FRONTEND, OTHER):
        res = client.get("/health", headers={"Origin": origin})
        assert "access-control-allow-origin" not in res.headers
