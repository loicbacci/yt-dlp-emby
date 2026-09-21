import stat

import pytest

pytest.importorskip("fastapi")

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app
from yt_dlp_emby.server.auth import AUTH_FILENAME, load_auth, verify_password

pytestmark = pytest.mark.web


def test_setup_required_on_empty_data_dir(client, tmp_path) -> None:
    response = client.get("/api/session")
    assert response.status_code == 200
    assert response.json() == {"setup_required": True, "authenticated": False}


def test_setup_creates_auth_file_and_logs_in(client, tmp_path) -> None:
    response = client.post("/api/setup", json={"password": "secretpass"})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    auth_path = tmp_path / AUTH_FILENAME
    assert auth_path.is_file()
    assert stat.S_IMODE(auth_path.stat().st_mode) == 0o600
    session = client.get("/api/session")
    assert session.json()["authenticated"] is True
    assert session.json()["setup_required"] is False


def test_setup_rejects_short_password(client) -> None:
    response = client.post("/api/setup", json={"password": "short"})
    assert response.status_code == 400


def test_setup_twice_returns_409(client) -> None:
    client.post("/api/setup", json={"password": "secretpass"})
    response = client.post("/api/setup", json={"password": "anotherpass"})
    assert response.status_code == 409


def test_login_and_logout(client) -> None:
    client.post("/api/setup", json={"password": "secretpass"})
    client.post("/api/logout")
    session = client.get("/api/session")
    assert session.json()["authenticated"] is False
    bad = client.post("/api/login", json={"password": "wrongpass"})
    assert bad.status_code == 401
    good = client.post("/api/login", json={"password": "secretpass"})
    assert good.status_code == 200
    assert client.get("/api/session").json()["authenticated"] is True


def test_protected_route_returns_401(client) -> None:
    response = client.get("/api/runs")
    assert response.status_code == 401
    body = response.json()
    assert body["error"] == "unauthorized"
    assert body["setup_required"] is True


def test_env_password_bootstrap_no_auto_login(tmp_path, monkeypatch) -> None:
    environ = {"YT_DLP_EMBY_PASSWORD": "bootstrapsecret"}
    with TestClient(create_app(data_dir=tmp_path, environ=environ)) as client:
        session = client.get("/api/session")
        assert session.json()["setup_required"] is False
        assert session.json()["authenticated"] is False
        auth = load_auth(tmp_path, environ)
        assert verify_password("bootstrapsecret", auth)
        assert "YT_DLP_EMBY_PASSWORD" not in environ
