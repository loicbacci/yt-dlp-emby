import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app
from yt_dlp_emby.server.manifests import read_manifest

pytestmark = pytest.mark.web


def _authed_client(tmp_path) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path, environ={}))
    client.post("/api/setup", json={"password": "secretpass"})
    return client


def test_get_missing_returns_example(tmp_path) -> None:
    client = _authed_client(tmp_path)
    response = client.get("/api/manifests/youtube")
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert "Example Channel" in body["text"]
    assert not (tmp_path / "youtube.yaml").exists()


def test_put_creates_and_validates(tmp_path) -> None:
    client = _authed_client(tmp_path)
    text = f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
"""
    response = client.put("/api/manifests/youtube", json={"text": text})
    assert response.status_code == 200
    assert response.json()["exists"] is True
    assert (tmp_path / "youtube.yaml").is_file()


def test_put_keeps_invalid_yaml_on_disk(tmp_path) -> None:
    client = _authed_client(tmp_path)
    bad = "library: /lib\nold_dir: /old\nseries: []\n"
    response = client.put("/api/manifests/youtube", json={"text": bad})
    assert response.status_code == 400
    assert (tmp_path / "youtube.yaml").is_file()
    assert "series" in response.json()["detail"]["error"].lower()


def test_unknown_kind_404(tmp_path) -> None:
    client = _authed_client(tmp_path)
    assert client.get("/api/manifests/other").status_code == 404


def test_read_manifest_rejects_traversal(tmp_path) -> None:
    with pytest.raises(ValueError):
        read_manifest(tmp_path, "..")
