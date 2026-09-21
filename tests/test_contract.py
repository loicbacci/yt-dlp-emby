"""Contract snapshot: /openapi.json routes vs web/src/api.ts client paths.

Fails on route/envelope drift between the FastAPI backend and the SPA client.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app

pytestmark = pytest.mark.web

REPO_ROOT = Path(__file__).resolve().parent.parent
API_TS = REPO_ROOT / "web" / "src" / "api.ts"

# Double-quoted literals: api<...>("/api/...").
_LITERAL_RE = re.compile(r'"(/api/[^"]*)"')
# Template prefixes: api<...>(`/api/...${...}`) — capture the static head.
_TEMPLATE_RE = re.compile(r"`(/api/[^`$]*)")

# Client paths with no server route (yet) that are safe to call.
# Keep this small and documented; everything else must exist in openapi.json.
ALLOWLIST: dict[str, str] = {
    # Optional batch endpoint: api.ts getSeriesMissingBatch falls back to
    # per-item GET /api/series/{platform}/{slug}/missing on 404/405.
    "/api/series/missing": "optional batch endpoint with client fallback",
}

# Dynamic series sub-routes built at runtime by seriesUrl(platform, slug, suffix)
# in api.ts — not visible as string literals, so lock the templates explicitly.
EXPECTED_SERIES_TEMPLATES = [
    "/api/series",
    "/api/series/{platform}/{slug}",
    "/api/series/{platform}/{slug}/disk",
    "/api/series/{platform}/{slug}/missing",
    "/api/series/{platform}/{slug}/sources",
    "/api/series/{platform}/{slug}/sources/{source_id}",
    "/api/series/{platform}/{slug}/sources/{source_id}/refresh",
    "/api/series/{platform}/{slug}/sources/{source_id}/seasons/{season_id}/episodes",
    "/api/series/dropout/{slug}/check",
    "/api/series/dropout/{slug}/layout",
]


def _openapi_paths(tmp_path: Path) -> dict:
    with TestClient(create_app(data_dir=tmp_path, environ={})) as client:
        response = client.get("/openapi.json")
        assert response.status_code == 200
        return response.json()["paths"]


def _client_paths() -> tuple[set[str], set[str]]:
    text = API_TS.read_text(encoding="utf-8")
    literals = {_strip_query(m) for m in _LITERAL_RE.findall(text)}
    templates = {_strip_query(m) for m in _TEMPLATE_RE.findall(text)}
    return literals, templates


def _strip_query(path: str) -> str:
    return path.split("?", 1)[0]


def _template_regex(template: str) -> re.Pattern[str]:
    # /api/series/{platform}/{slug} -> ^/api/series/[^/]+/[^/]+$
    parts = re.split(r"(\{[^}]+\})", template)
    pattern = "".join("[^/]+" if part.startswith("{") else re.escape(part) for part in parts)
    return re.compile(f"^{pattern}$")


def test_client_literals_exist_in_openapi(tmp_path: Path) -> None:
    """Every "/api/..." literal in api.ts must match an openapi route."""
    openapi = _openapi_paths(tmp_path)
    regexes = [_template_regex(t) for t in openapi]
    literals, _ = _client_paths()
    assert literals, "expected to find /api literals in web/src/api.ts"
    missing = [
        path
        for path in sorted(literals)
        if path not in ALLOWLIST and not any(rx.match(path) for rx in regexes)
    ]
    assert not missing, f"client paths missing from openapi.json: {missing}"


def test_client_template_prefixes_exist_in_openapi(tmp_path: Path) -> None:
    """Template-built prefixes (`/api/...${...}`) must anchor to openapi routes."""
    openapi = _openapi_paths(tmp_path)
    _, templates = _client_paths()
    # Only keep true prefixes (templates cut at the first ${...}).
    prefixes = {t for t in templates if t.endswith("/")}
    assert prefixes, "expected template prefixes in web/src/api.ts"
    for prefix in sorted(prefixes):
        assert any(route == prefix.rstrip("/") or route.startswith(prefix) for route in openapi), (
            f"no openapi route under client prefix {prefix!r}"
        )


def test_series_dynamic_templates_present(tmp_path: Path) -> None:
    """seriesUrl() suffix routes must exist in openapi (dynamic, not literals)."""
    openapi = _openapi_paths(tmp_path)
    for template in EXPECTED_SERIES_TEMPLATES:
        assert template in openapi, f"missing openapi route {template}"


def test_error_envelope_shape(tmp_path: Path) -> None:
    """Errors use {"error": ...}; legacy {"detail": ...} stays parseable.

    Backend ships the new {"error": ...} envelope first; api.ts
    messageFromErrorBody() normalizes both shapes during rollout, so a
    legacy {"detail": ...} body must never crash the client either.
    """
    with TestClient(create_app(data_dir=tmp_path, environ={})) as client:
        client.post("/api/setup", json={"password": "secretpass"})

        not_found = client.get("/api/does-not-exist")
        assert not_found.status_code == 404
        assert "error" in not_found.json(), not_found.text

        bad_kind = client.get("/api/manifests/other")
        assert bad_kind.status_code == 404
        assert "error" in bad_kind.json(), bad_kind.text

        invalid = client.put("/api/manifests/youtube", json={"nope": True})
        assert invalid.status_code == 400
        assert "error" in invalid.json(), invalid.text

    with TestClient(create_app(data_dir=tmp_path, environ={})) as fresh:
        unauthorized = fresh.get("/api/runs")
        assert unauthorized.status_code == 401
        assert "error" in unauthorized.json(), unauthorized.text
