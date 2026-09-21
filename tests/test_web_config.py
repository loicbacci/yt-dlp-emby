import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app

pytestmark = pytest.mark.web


def _authed_ctx(tmp_path, environ=None) -> TestClient:
    """Client with custom environ; the caller must `with` it for lifespan exit."""
    client = TestClient(create_app(data_dir=tmp_path, environ=environ or {}))
    client.post("/api/setup", json={"password": "secretpass"})
    return client


def test_config_requires_auth(client) -> None:
    assert client.get("/api/config").status_code == 401


def test_get_config_missing_file(authed_client, tmp_path) -> None:
    client = authed_client
    body = client.get("/api/config").json()
    assert body["exists"] is False
    assert body["path"].endswith("config.toml")
    assert body["fields"]["library"]["source"] == "unset"
    assert body["fields"]["library"]["section"] == "fallback"
    assert body["fields"]["sonarr_url"]["section"] == "root"


def test_put_config_writes_fallback_table(authed_client, tmp_path) -> None:
    client = authed_client
    library = tmp_path / "lib"
    old_dir = tmp_path / "old"
    library.mkdir()
    old_dir.mkdir()
    response = client.put(
        "/api/config",
        json={
            "library": str(library),
            "old_dir": str(old_dir),
            "staging": "",
            "bench_dest": "",
            "sonarr_url": "http://sonarr:8989",
            "sonarr_api_key": "secret",
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is True
    assert body["fields"]["library"]["file"] == str(library)
    assert body["fields"]["library"]["source"] == "file"
    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert "[fallback]" in text
    assert f'library = "{library}"' in text
    assert 'sonarr_api_key = "secret"' in text


def test_put_config_rejects_bad_sonarr_url(authed_client, tmp_path) -> None:
    client = authed_client
    response = client.put(
        "/api/config",
        json={"sonarr_url": "sonarr.local"},
    )
    assert response.status_code == 400
    assert "http" in response.json()["error"]


def test_get_config_env_overlay(tmp_path) -> None:
    (tmp_path / "config.toml").write_text(
        '[fallback]\nlibrary = "/from/file/lib"\nold_dir = "/from/file/old"\n',
        encoding="utf-8",
    )
    client = _authed_ctx(tmp_path, {"YT_DLP_EMBY_LIBRARY": "/from/env/lib"})
    with client:
        body = client.get("/api/config").json()
        field = body["fields"]["library"]
        assert field["source"] == "env"
        assert field["env_name"] == "YT_DLP_EMBY_LIBRARY"
        assert field["file"] == "/from/file/lib"
        assert field["effective"] == "/from/env/lib"


def test_validate_manifest_without_paths_uses_fallback(authed_client, tmp_path) -> None:
    (tmp_path / "config.toml").write_text(
        '[fallback]\nlibrary = "/from/fallback/lib"\nold_dir = "/from/fallback/old"\n',
        encoding="utf-8",
    )
    client = authed_client
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


def test_sonarr_ping_requires_auth(client) -> None:
    assert client.post("/api/sonarr/ping", json={}).status_code == 401


def test_sonarr_ping_ok(authed_client, tmp_path, monkeypatch) -> None:
    def fake_ping(*, base_url: str, api_key: str, get_json=None):
        assert base_url == "http://sonarr:8989"
        assert api_key == "secret"
        return {"ok": True, "version": "4.0.1", "instance": "Home"}

    monkeypatch.setattr("yt_dlp_emby.server.app.ping_sonarr", fake_ping)
    client = authed_client
    response = client.post(
        "/api/sonarr/ping",
        json={"sonarr_url": "http://sonarr:8989", "sonarr_api_key": "secret"},
    )
    assert response.status_code == 200
    assert response.json() == {
        "ok": True,
        "version": "4.0.1",
        "instance": "Home",
    }


def test_sonarr_ping_uses_saved_config(authed_client, tmp_path, monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_ping(*, base_url: str, api_key: str, get_json=None):
        seen["url"] = base_url
        seen["key"] = api_key
        return {"ok": True, "version": None, "instance": None}

    monkeypatch.setattr("yt_dlp_emby.server.app.ping_sonarr", fake_ping)
    client = authed_client
    client.put(
        "/api/config",
        json={"sonarr_url": "http://from-file:8989", "sonarr_api_key": "file-key"},
    )
    response = client.post("/api/sonarr/ping", json={})
    assert response.status_code == 200
    assert seen == {"url": "http://from-file:8989", "key": "file-key"}


def test_sonarr_ping_prefers_body_then_env(tmp_path, monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_ping(*, base_url: str, api_key: str, get_json=None):
        seen["url"] = base_url
        seen["key"] = api_key
        return {"ok": True, "version": "4.0.0", "instance": "Sonarr"}

    monkeypatch.setattr("yt_dlp_emby.server.app.ping_sonarr", fake_ping)
    client = _authed_ctx(
        tmp_path,
        {
            "YT_DLP_EMBY_SONARR_URL": "http://from-env:8989",
            "YT_DLP_EMBY_SONARR_API_KEY": "env-key",
        },
    )
    with client:
        response = client.post("/api/sonarr/ping", json={})
        assert response.status_code == 200
        assert seen == {"url": "http://from-env:8989", "key": "env-key"}


def test_sonarr_ping_missing(authed_client, tmp_path) -> None:
    client = authed_client
    response = client.post("/api/sonarr/ping", json={})
    assert response.status_code == 400
    assert "required" in response.json()["error"]


def test_sonarr_ping_bad_url(authed_client, tmp_path) -> None:
    client = authed_client
    response = client.post(
        "/api/sonarr/ping",
        json={"sonarr_url": "sonarr.local", "sonarr_api_key": "secret"},
    )
    assert response.status_code == 400
    assert "http" in response.json()["error"]


def test_sonarr_ping_config_error(authed_client, tmp_path, monkeypatch) -> None:
    from yt_dlp_emby.config import ConfigError

    def fake_ping(*, base_url: str, api_key: str, get_json=None):
        raise ConfigError("Sonarr API key rejected")

    monkeypatch.setattr("yt_dlp_emby.server.app.ping_sonarr", fake_ping)
    client = authed_client
    response = client.post(
        "/api/sonarr/ping",
        json={"sonarr_url": "http://sonarr:8989", "sonarr_api_key": "bad"},
    )
    assert response.status_code == 400
    assert response.json()["error"] == "Sonarr API key rejected"


def test_sonarr_episodes_uses_env(tmp_path, monkeypatch) -> None:
    seen: dict[str, str] = {}

    def fake_fetch(tvdb_id, *, base_url, api_key, cache_path, force_refetch=False, get_json=None):
        seen["url"] = base_url
        seen["key"] = api_key
        assert tvdb_id == 123
        from yt_dlp_emby.sonarr import SonarrEpisode

        return "Show", [SonarrEpisode(1, 1, "Pilot", "2020-01-01")], "show"

    monkeypatch.setattr("yt_dlp_emby.server.app.fetch_episodes_cached_meta", fake_fetch)
    client = _authed_ctx(
        tmp_path,
        {
            "YT_DLP_EMBY_SONARR_URL": "http://from-env:8989",
            "YT_DLP_EMBY_SONARR_API_KEY": "env-key",
        },
    )
    with client:
        response = client.get("/api/sonarr/episodes", params={"tvdb_id": 123})
        assert response.status_code == 200
        assert seen == {"url": "http://from-env:8989", "key": "env-key"}
        assert response.json()["title"] == "Show"
