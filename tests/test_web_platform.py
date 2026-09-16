import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app

pytestmark = pytest.mark.web


def _authed(tmp_path) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path, environ={}))
    client.post("/api/setup", json={"password": "secretpass"})
    return client


def test_platform_put_preserves_imports(tmp_path) -> None:
    root = tmp_path / "dropout.yaml"
    root.write_text(
        'imports:\n  - shows/x.yaml\nlibrary: "/old"\nseries: []\n',
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    client.put(
        "/api/platform/dropout",
        json={"library": "/new/lib", "old_dir": "", "cookies": ""},
    )
    text = root.read_text(encoding="utf-8")
    assert "shows/x.yaml" in text
    assert "/new/lib" in text


def test_platform_get(tmp_path) -> None:
    (tmp_path / "youtube.yaml").write_text(
        'library: "/yt"\nold_dir: "/old"\n',
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    body = client.get("/api/platform/youtube").json()
    assert body["library"] == "/yt"
    assert body["old_dir"] == "/old"
