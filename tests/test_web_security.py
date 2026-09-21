"""Security and API-shape tests for the web backend."""

from __future__ import annotations

import stat

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import COOKIE_NAME, create_app
from yt_dlp_emby.server.auth import AUTH_FILENAME

pytestmark = pytest.mark.web


def _seed_dropout_series(tmp_path) -> None:
    (tmp_path / "dropout.yaml").write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\nseries: []\n",
        encoding="utf-8",
    )


def test_login_sixth_attempt_is_429(tmp_path) -> None:
    environ = {"YT_DLP_EMBY_PASSWORD": "bootstrapsecret"}
    with TestClient(create_app(data_dir=tmp_path, environ=environ)) as client:
        statuses = [
            client.post("/api/login", json={"password": "wrongpass1"}).status_code for _ in range(6)
        ]
        assert statuses[:5] == [401, 401, 401, 401, 401]
        assert statuses[5] == 429


def test_oversized_password_is_400(client) -> None:
    response = client.post("/api/setup", json={"password": "x" * 129})
    assert response.status_code == 400
    assert "error" in response.json()


def test_config_masks_sonarr_api_key(authed_client, tmp_path) -> None:
    client = authed_client
    put = client.put(
        "/api/config",
        json={"sonarr_url": "http://sonarr.example:8989", "sonarr_api_key": "supersecret"},
    )
    assert put.status_code == 200
    body = client.get("/api/config").json()
    field = body["fields"]["sonarr_api_key"]
    assert field["file"] == {"set": True, "masked": "****cret"}
    assert field["effective"] == {"set": True, "masked": "****cret"}
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "supersecret" in text


def test_auth_file_mode_600(authed_client, tmp_path) -> None:
    path = tmp_path / AUTH_FILENAME
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_add_source_rejects_ssrf(authed_client, tmp_path) -> None:
    _seed_dropout_series(tmp_path)
    client = authed_client
    created = client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show"},
    )
    assert created.status_code == 200, created.text
    for url in (
        "http://127.0.0.1/secret",
        "http://169.254.169.254/latest",
        "file:///etc/passwd",
    ):
        response = client.post(
            "/api/series/dropout/show/sources",
            json={"url": url},
        )
        assert response.status_code == 400, (url, response.text)
        assert response.status_code != 500


def test_svg_poster_404(authed_client, tmp_path, monkeypatch) -> None:
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>"

    def fake_poster(*_args, **_kwargs):
        from yt_dlp_emby.images import jpeg_bytes_from_image

        try:
            return jpeg_bytes_from_image(svg)
        except ValueError:
            return None

    monkeypatch.setattr("yt_dlp_emby.sonarr.fetch_sonarr_poster", fake_poster)
    _seed_dropout_series(tmp_path)
    client = authed_client
    created = client.post(
        "/api/series",
        json={"name": "Solo", "platform": "dropout", "path": "Solo", "tvdb_id": 99},
    )
    assert created.status_code == 200, created.text
    response = client.get("/api/series/dropout/solo/poster")
    assert response.status_code == 404


def test_put_series_fuzz_never_500(authed_client, tmp_path) -> None:
    _seed_dropout_series(tmp_path)
    client = authed_client
    created = client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show"},
    )
    assert created.status_code == 200, created.text
    payloads = [
        {},
        {"name": "Show", "path": "Show", "sources": [{"extra": True}]},
        {"name": "Show", "path": "Show", "sources": [{"url": 1, "seasons": []}]},
        {"name": "Show", "path": "Show", "sources": [{"seasons": [{"dropout": "nope"}]}]},
        {"name": "Show", "path": "Show", "tvdb_id": "nope", "sources": []},
    ]
    for payload in payloads:
        response = client.put("/api/series/dropout/show", json=payload)
        assert response.status_code < 500, payload
        assert response.status_code == 400


def test_password_rotate_requires_current(tmp_path) -> None:
    # Share one app instance: the live middleware must pick up the rotated
    # secret (a fresh app would reload it from disk and hide the bug).
    app = create_app(data_dir=tmp_path, environ={})
    with TestClient(app) as client:
        client.post("/api/setup", json={"password": "secretpass"})
        old_cookie = client.cookies.get(COOKIE_NAME)
        assert old_cookie
        bad = client.post(
            "/api/password",
            json={"current": "nopepass", "password": "newsecret1"},
        )
        assert bad.status_code == 400
        good = client.post(
            "/api/password",
            json={"current": "secretpass", "password": "newsecret1"},
        )
        assert good.status_code == 200
        # Rotation forces logout-all: the pre-rotation cookie must now 401.
        # `stale` shares the entered app above, so no second lifespan is needed.
        stale = TestClient(app)
        stale.cookies.set(COOKIE_NAME, old_cookie)
        assert stale.get("/api/runs").status_code == 401
        client.post("/api/logout")
        assert client.post("/api/login", json={"password": "newsecret1"}).status_code == 200


def test_csrf_rejects_cross_origin(authed_client, tmp_path) -> None:
    client = authed_client
    response = client.post(
        "/api/logout",
        headers={"Origin": "https://evil.example", "Host": "testserver"},
    )
    assert response.status_code == 403


def test_refresh_async_returns_202(authed_client, tmp_path) -> None:
    _seed_dropout_series(tmp_path)
    client = authed_client
    client.post("/api/series", json={"name": "Show", "platform": "dropout", "path": "Show"})
    response = client.post(
        "/api/series/refresh",
        json={"items": [{"platform": "dropout", "slug": "show"}]},
    )
    assert response.status_code == 202
    job_id = response.json()["job_id"]
    polled = client.get(f"/api/series/refresh/{job_id}")
    assert polled.status_code == 200
    assert polled.json()["status"] in {"running", "done", "error"}


def test_concurrent_series_edit_409(authed_client, tmp_path) -> None:
    (tmp_path / "youtube.yaml").write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: Example Channel\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLaaaa\n",
        encoding="utf-8",
    )
    client = authed_client
    client.app.state.runner._state.status = "running"
    detail = client.get("/api/series/youtube/example-channel")
    assert detail.status_code == 200, detail.text
    body = detail.json()
    response = client.put("/api/series/youtube/example-channel", json=body)
    assert response.status_code == 409
    assert "progress" in response.json()["error"]


def test_put_import_path_in_url(authed_client, tmp_path) -> None:
    (tmp_path / "shows").mkdir()
    (tmp_path / "dropout.yaml").write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\n"
        "imports:\n  - shows/show.yaml\nseries: []\n",
        encoding="utf-8",
    )
    client = authed_client
    text = (
        "series:\n  - name: Show\n    path: Show\n"
        "    url: https://watch.dropout.tv/show\n    seasons:\n      - dropout: 1\n"
    )
    response = client.put(
        "/api/manifests/dropout/imports/shows/show.yaml",
        json={"text": text},
    )
    assert response.status_code == 200, response.text
    assert (tmp_path / "shows" / "show.yaml").is_file()
