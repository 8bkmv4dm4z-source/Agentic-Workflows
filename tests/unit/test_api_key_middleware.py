"""Unit tests for APIKeyMiddleware."""

from __future__ import annotations

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from agentic_workflows.api.middleware.api_key import APIKeyMiddleware


def _build_app() -> FastAPI:
    """Minimal FastAPI app with APIKeyMiddleware and two routes."""
    app = FastAPI()
    app.add_middleware(APIKeyMiddleware)

    @app.get("/health")
    async def health():
        return JSONResponse(content={"status": "ok"})

    @app.get("/test")
    async def test_route():
        return JSONResponse(content={"data": "protected"})

    return app


@pytest.mark.asyncio
async def test_api_key_set_no_header_returns_401(monkeypatch):
    """With API_KEY set, a request without the header gets 401."""
    monkeypatch.setenv("API_KEY", "secret123")
    app = _build_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/test")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_api_key_set_correct_header_returns_200(monkeypatch):
    """With API_KEY set, correct X-API-Key header passes through."""
    monkeypatch.setenv("API_KEY", "secret123")
    app = _build_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/test", headers={"X-API-Key": "secret123"})
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_key_set_wrong_header_returns_401(monkeypatch):
    """With API_KEY set, an incorrect key gets 401."""
    monkeypatch.setenv("API_KEY", "secret123")
    app = _build_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/test", headers={"X-API-Key": "wrong"})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_health_exempt_without_header(monkeypatch):
    """With API_KEY set, /health is accessible without the header."""
    monkeypatch.setenv("API_KEY", "secret123")
    app = _build_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_api_key_unset_passes_through(monkeypatch):
    """Without API_KEY env var, all requests pass through (dev mode)."""
    monkeypatch.delenv("API_KEY", raising=False)
    app = _build_app()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/test")
    assert resp.status_code == 200
