"""The murmurent logo (murmuration animation) is served for the dashboard
header widget + the VSCode companion window (Mike's request)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from murmurent.dashboard.server import create_app


def test_murmuration_route_serves_the_wordmark_animation():
    r = TestClient(create_app()).get("/murmuration")
    assert r.status_code == 200
    assert "text/html" in r.headers.get("content-type", "")
    body = r.text
    # It's the uniform-wordmark file, and it carries logo mode (chrome-free).
    assert '<canvas id="stage">' in body
    assert "html.logo #mark" in body          # logo-mode CSS
    assert "logoMode" in body                 # logo-mode JS (auto-play, no veil)
