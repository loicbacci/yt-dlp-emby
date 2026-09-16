import json

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app

pytestmark = pytest.mark.web

SECRET = "super-secret-cookie-value"
NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    f".youtube.com\tTRUE\t/\tTRUE\t0\tSID\t{SECRET}\n"
)


def _authed(tmp_path, environ=None) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path, environ=environ or {}))
    client.post("/api/setup", json={"password": "secretpass"})
    return client


def test_cookies_require_auth(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path, environ={}))
    assert client.get("/api/cookies").status_code == 401
    assert client.put("/api/cookies/youtube", json={"text": NETSCAPE}).status_code == 401


def test_get_cookies_status_without_text(tmp_path) -> None:
    (tmp_path / "cookies.txt").write_text(NETSCAPE, encoding="utf-8")
    client = _authed(tmp_path)
    response = client.get("/api/cookies")
    assert response.status_code == 200
    body = response.json()
    raw = json.dumps(body)
    assert SECRET not in raw
    assert "SID" not in raw
    assert body["jars"]["youtube"]["exists"] is True
    assert body["jars"]["youtube"]["usable"] is True
    assert body["jars"]["youtube"]["filename"] == "cookies.txt"
    assert body["jars"]["dropout"]["exists"] is False
    assert body["env_set"] is False


def test_put_cookies_writes_jars_and_returns_status_only(tmp_path) -> None:
    client = _authed(tmp_path)
    youtube = client.put("/api/cookies/youtube", json={"text": NETSCAPE})
    dropout = client.put(
        "/api/cookies/dropout",
        json={
            "text": "# Netscape HTTP Cookie File\n"
            ".watch.dropout.tv\tTRUE\t/\tTRUE\t0\t_session\tabc\n"
        },
    )
    assert youtube.status_code == 200
    assert dropout.status_code == 200
    assert SECRET not in json.dumps(youtube.json())
    assert (tmp_path / "cookies.txt").read_text(encoding="utf-8") == NETSCAPE
    assert (tmp_path / "dropout-cookies.txt").is_file()
    body = client.get("/api/cookies").json()
    assert body["jars"]["youtube"]["usable"] is True
    assert body["jars"]["dropout"]["usable"] is True
    assert SECRET not in json.dumps(body)


def test_put_cookies_rejects_empty_and_unknown(tmp_path) -> None:
    client = _authed(tmp_path)
    empty = client.put(
        "/api/cookies/youtube", json={"text": "# Netscape HTTP Cookie File\n"}
    )
    assert empty.status_code == 400
    assert "empty" in empty.json()["detail"]["error"]
    assert client.put("/api/cookies/other", json={"text": NETSCAPE}).status_code == 404


def test_put_cookies_uses_yaml_relative_filename(tmp_path) -> None:
    (tmp_path / "dropout.yaml").write_text(
        "library: /lib\ncookies: custom-drop.txt\nseries: []\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    resp = client.put(
        "/api/cookies/dropout",
        json={
            "text": "# Netscape HTTP Cookie File\n"
            ".watch.dropout.tv\tTRUE\t/\tTRUE\t0\t_session\tabc\n"
        },
    )
    assert resp.status_code == 200
    assert (tmp_path / "custom-drop.txt").is_file()
    assert not (tmp_path / "dropout-cookies.txt").exists()
    platform = client.get("/api/platform/dropout").json()
    assert platform["cookies"] == "custom-drop.txt"
    assert platform["cookie_jar"]["filename"] == "custom-drop.txt"
    assert platform["cookie_jar"]["usable"] is True


def test_put_cookies_sets_yaml_field_when_missing(tmp_path) -> None:
    (tmp_path / "youtube.yaml").write_text(
        "library: /lib\nseries: []\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    resp = client.put("/api/cookies/youtube", json={"text": NETSCAPE})
    assert resp.status_code == 200
    root = (tmp_path / "youtube.yaml").read_text(encoding="utf-8")
    assert "cookies: cookies.txt" in root
    platform = client.get("/api/platform/youtube").json()
    assert platform["cookies"] == "cookies.txt"
    assert platform["cookie_jar"]["filename"] == "cookies.txt"
    assert platform["cookie_jar"]["usable"] is True


def test_get_cookies_env_overlay(tmp_path) -> None:
    client = _authed(tmp_path, {"YT_DLP_EMBY_COOKIES": "/from/env/cookies.txt"})
    body = client.get("/api/cookies").json()
    assert body["env_set"] is True
    assert body["env_name"] == "YT_DLP_EMBY_COOKIES"
    assert body["env_path"] == "/from/env/cookies.txt"
