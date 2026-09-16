import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app

pytestmark = pytest.mark.web


def _authed(tmp_path, environ=None) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path, environ=environ or {}))
    client.post("/api/setup", json={"password": "secretpass"})
    return client


def test_config_requires_auth(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path, environ={}))
    assert client.get("/api/config").status_code == 401


def test_get_config_missing_file(tmp_path) -> None:
    client = _authed(tmp_path)
    body = client.get("/api/config").json()
    assert body["exists"] is False
    assert body["path"].endswith("config.toml")
    assert body["fields"]["library"]["source"] == "unset"
    assert body["fields"]["library"]["section"] == "fallback"
    assert body["fields"]["sonarr_url"]["section"] == "root"


def test_put_config_writes_fallback_table(tmp_path) -> None:
    client = _authed(tmp_path)
    response = client.put(
        "/api/config",
        json={
            "library": "/media/lib",
            "old_dir": "/media/old",
            "staging": "",
            "bench_dest": "",
            "sonarr_url": "http://sonarr:8989",
            "sonarr_api_key": "secret",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["fields"]["library"]["file"] == "/media/lib"
    assert body["fields"]["library"]["source"] == "file"
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "[fallback]" in text
    assert 'library = "/media/lib"' in text
    assert 'sonarr_api_key = "secret"' in text


def test_put_config_rejects_bad_sonarr_url(tmp_path) -> None:
    client = _authed(tmp_path)
    response = client.put(
        "/api/config",
        json={"sonarr_url": "sonarr.local"},
    )
    assert response.status_code == 400
    assert "http" in response.json()["detail"]["error"]


def test_get_config_env_overlay(tmp_path) -> None:
    (tmp_path / "config.toml").write_text(
        '[fallback]\nlibrary = "/from/file/lib"\nold_dir = "/from/file/old"\n',
        encoding="utf-8",
    )
    client = _authed(tmp_path, {"YT_DLP_EMBY_LIBRARY": "/from/env/lib"})
    body = client.get("/api/config").json()
    field = body["fields"]["library"]
    assert field["source"] == "env"
    assert field["env_name"] == "YT_DLP_EMBY_LIBRARY"
    assert field["file"] == "/from/file/lib"
    assert field["effective"] == "/from/env/lib"


def test_validate_manifest_without_paths_uses_fallback(tmp_path) -> None:
    (tmp_path / "config.toml").write_text(
        '[fallback]\nlibrary = "/from/fallback/lib"\nold_dir = "/from/fallback/old"\n',
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    text = """
series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
"""
    response = client.post("/api/manifests/youtube/validate", json={"text": text})
    assert response.status_code == 200
    paths = response.json()["paths"]
    assert paths["library"]["source"] == "fallback"
    assert paths["library"]["effective"] == "/from/fallback/lib"
    assert paths["old_dir"]["source"] == "fallback"
