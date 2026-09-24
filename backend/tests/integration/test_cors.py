"""CORS must allow the frontend's dev origin to call this API from a
browser -- see frontend/AGENTS.md's core flows, all of which are
fetch() calls from a different origin (localhost:3000 vs. this API's
localhost:8000) with no server-side proxy in between."""

from api.config import settings


def test_preflight_allows_configured_frontend_origin(client):
    resp = client.options(
        "/health",
        headers={
            "Origin": settings.frontend_origin,
            "Access-Control-Request-Method": "GET",
        },
    )

    assert resp.status_code == 200
    assert resp.headers["access-control-allow-origin"] == settings.frontend_origin


def test_actual_request_echoes_allow_origin_header(client):
    resp = client.get("/health", headers={"Origin": settings.frontend_origin})

    assert resp.headers["access-control-allow-origin"] == settings.frontend_origin


def test_unlisted_origin_is_not_granted_cors_headers(client):
    resp = client.get("/health", headers={"Origin": "https://evil.example.com"})

    assert "access-control-allow-origin" not in resp.headers
