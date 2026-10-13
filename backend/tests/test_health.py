"""Smoke tests for the API shell."""

from __future__ import annotations

import pytest

from app import main


async def test_root_says_hello(api):
    response = await api.get("/")
    assert response.status_code == 200
    assert response.json()["name"] == "Swarm"


async def test_health_reports_database_down_without_failing(api, monkeypatch):
    async def broken() -> str:
        return "unavailable"

    monkeypatch.setattr(main, "_database_status", broken)
    response = await api.get("/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "version": "0.1.0",
        "env": main.get_settings().app_env,
        "database": "unavailable",
    }


@pytest.mark.db
async def test_health_sees_the_database(api):
    response = await api.get("/health")
    assert response.json()["database"] == "ok"


async def test_large_json_is_compressed_and_small_answers_are_not(api):
    docs = await api.get("/openapi.json", headers={"Accept-Encoding": "gzip"})
    assert docs.headers.get("content-encoding") == "gzip"
    small = await api.get("/health", headers={"Accept-Encoding": "gzip"})
    assert "content-encoding" not in small.headers
