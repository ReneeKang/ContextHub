"""Smoke: chat routes registered (Swagger/OpenAPI)."""

from __future__ import annotations

from app.main import app


def test_chat_query_and_generate_routes_exist() -> None:
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/api/v1/chat/query" in paths
    assert "/api/v1/chat/discover" in paths
    assert "/api/v1/chat/generate" in paths


def test_poc_ui_routes_exist() -> None:
    paths = {getattr(r, "path", "") for r in app.routes}
    assert "/" in paths
    assert "/poc" in paths


def test_poc_static_mount_registered() -> None:
    names = {getattr(r, "name", "") for r in app.routes}
    assert "poc_static" in names
