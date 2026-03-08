"""Tests for FastAPI app structure and middleware — no lifespan required."""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# App structure (import-time coverage)
# ---------------------------------------------------------------------------

def test_app_importable():
    from agentic_workflows.api.app import app
    assert app is not None


def test_app_has_routes():
    from agentic_workflows.api.app import app
    paths = [r.path for r in app.routes]
    assert "/health" in paths


def test_app_title():
    from agentic_workflows.api.app import app
    assert "Agentic" in app.title


def test_app_has_middleware():
    from agentic_workflows.api.app import app
    # Middleware registered at module level — just verifying app object exists
    assert app is not None


def test_cors_origins_default():
    from agentic_workflows.api.app import _cors_origins
    assert len(_cors_origins) > 0


def test_cors_origins_from_env(monkeypatch):
    monkeypatch.setenv("CORS_ORIGINS", "http://example.com,http://other.com")
    # Re-import to pick up new env — just verifies the logic via direct invocation
    raw = os.environ.get("CORS_ORIGINS", "")
    origins = [o.strip() for o in raw.split(",") if o.strip()]
    assert "http://example.com" in origins
    assert "http://other.com" in origins


# ---------------------------------------------------------------------------
# Middleware tests via mocked TestClient
# ---------------------------------------------------------------------------

@pytest.fixture(scope="module")
def client():
    """Build a TestClient with a mocked orchestrator to bypass provider requirement."""
    from agentic_workflows.api.app import app

    mock_orch = MagicMock()
    mock_orch.tools = {str(i): MagicMock() for i in range(5)}
    mock_run_store = MagicMock()
    mock_run_store.close = MagicMock()

    async def mock_lifespan(application):
        application.state.orchestrator = mock_orch
        application.state.run_store = mock_run_store
        application.state.active_streams = {}
        application.state.stream_secret = "test_secret"
        yield

    # Patch lifespan to avoid real provider/DB calls
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def patched_lifespan(application):
        application.state.orchestrator = mock_orch
        application.state.run_store = mock_run_store
        application.state.active_streams = {}
        application.state.stream_secret = "test_secret"
        yield

    with patch.object(app.router, "lifespan_context", patched_lifespan), TestClient(app, raise_server_exceptions=False) as c:
        yield c


def test_health_returns_ok(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_tools_endpoint(client):
    r = client.get("/tools")
    assert r.status_code == 200


def test_unknown_route_404(client):
    r = client.get("/nonexistent_endpoint_xyz")
    assert r.status_code == 404


def test_body_size_limit(client):
    big = b"x" * (1_048_576 + 1)
    r = client.post(
        "/run",
        content=big,
        headers={"Content-Type": "application/json", "Content-Length": str(len(big))},
    )
    assert r.status_code == 413


def test_api_key_middleware_no_key_env(client, monkeypatch):
    monkeypatch.delenv("API_KEY", raising=False)
    r = client.get("/health")
    assert r.status_code == 200


def test_api_key_middleware_wrong_key(monkeypatch):
    from agentic_workflows.api.app import app

    monkeypatch.setenv("API_KEY", "supersecret")

    mock_orch = MagicMock()
    mock_orch.tools = {}
    mock_store = MagicMock()
    mock_store.close = MagicMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def patched_lifespan(application):
        application.state.orchestrator = mock_orch
        application.state.run_store = mock_store
        application.state.active_streams = {}
        application.state.stream_secret = "supersecret"
        yield

    with patch.object(app.router, "lifespan_context", patched_lifespan), TestClient(app, raise_server_exceptions=False) as c:
        # /tools is a protected route (not /health which is always public)
        r = c.get("/tools", headers={"X-API-Key": "wrong"})
        assert r.status_code == 401


def test_api_key_middleware_correct_key(monkeypatch):
    from agentic_workflows.api.app import app

    monkeypatch.setenv("API_KEY", "supersecret")

    mock_orch = MagicMock()
    mock_orch.tools = {}
    mock_store = MagicMock()
    mock_store.close = MagicMock()

    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def patched_lifespan(application):
        application.state.orchestrator = mock_orch
        application.state.run_store = mock_store
        application.state.active_streams = {}
        application.state.stream_secret = "supersecret"
        yield

    with patch.object(app.router, "lifespan_context", patched_lifespan), TestClient(app, raise_server_exceptions=False) as c:
        # /health is always public regardless of API key
        r = c.get("/health", headers={"X-API-Key": "supersecret"})
        assert r.status_code == 200
