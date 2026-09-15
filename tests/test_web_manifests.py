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


def test_put_rejects_invalid_without_writing(tmp_path) -> None:
    client = _authed_client(tmp_path)
    bad = "library: /lib\nold_dir: /old\nseries: []\n"
    response = client.put("/api/manifests/youtube", json={"text": bad})
    assert response.status_code == 400
    assert "series" in response.json()["detail"]["error"].lower()
    assert not (tmp_path / "youtube.yaml").exists()


def test_put_keeps_previous_file_when_invalid(tmp_path) -> None:
    client = _authed_client(tmp_path)
    good = f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
"""
    assert client.put("/api/manifests/youtube", json={"text": good}).status_code == 200
    original = (tmp_path / "youtube.yaml").read_text(encoding="utf-8")
    response = client.put(
        "/api/manifests/youtube",
        json={"text": "library: /lib\nold_dir: /old\nseries: []\n"},
    )
    assert response.status_code == 400
    assert (tmp_path / "youtube.yaml").read_text(encoding="utf-8") == original


def test_validate_rejects_invalid_yaml_syntax(tmp_path) -> None:
    client = _authed_client(tmp_path)
    response = client.post(
        "/api/manifests/youtube/validate",
        json={"text": "library: [\n"},
    )
    assert response.status_code == 400
    assert "invalid yaml" in response.json()["detail"]["error"].lower()


def test_validate_rejects_schema(tmp_path) -> None:
    client = _authed_client(tmp_path)
    response = client.post(
        "/api/manifests/youtube/validate",
        json={"text": "library: /lib\nold_dir: /old\nseries: []\n"},
    )
    assert response.status_code == 400
    assert "series" in response.json()["detail"]["error"].lower()


def test_validate_accepts_valid_manifest(tmp_path) -> None:
    client = _authed_client(tmp_path)
    text = f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Example Channel
    playlists:
      - url: https://www.youtube.com/playlist?list=PLaaaa
"""
    response = client.post("/api/manifests/youtube/validate", json={"text": text})
    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert not (tmp_path / "youtube.yaml").exists()


def test_validate_dropout_schema(tmp_path) -> None:
    client = _authed_client(tmp_path)
    bad = f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: Dimension 20
    path: Dimension 20
    seasons:
      - dropout: 1
"""
    response = client.post("/api/manifests/dropout/validate", json={"text": bad})
    assert response.status_code == 400
    assert "url" in response.json()["detail"]["error"].lower()


def test_unknown_kind_404(tmp_path) -> None:
    client = _authed_client(tmp_path)
    assert client.get("/api/manifests/other").status_code == 404


def test_read_manifest_rejects_traversal(tmp_path) -> None:
    with pytest.raises(ValueError):
        read_manifest(tmp_path, "..")


def _dropout_root(library: str, old_dir: str, imports: str = "") -> str:
    extra = f"\nimports:\n{imports}" if imports else ""
    series = ""
    if not imports:
        series = """
series:
  - name: Game Changer
    path: Game Changer
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
"""
    return f"library: {library}\nold_dir: {old_dir}{extra}\n{series}"


def test_get_dropout_imports_empty_without_key(tmp_path) -> None:
    client = _authed_client(tmp_path)
    (tmp_path / "dropout.yaml").write_text(
        _dropout_root(str(tmp_path / "lib"), str(tmp_path / "old")),
        encoding="utf-8",
    )
    body = client.get("/api/manifests/dropout").json()
    assert body["imports"] == []


def test_get_dropout_lists_relative_import(tmp_path) -> None:
    client = _authed_client(tmp_path)
    shows = tmp_path / "shows"
    shows.mkdir()
    child = shows / "game-changer.yaml"
    child.write_text(
        """
series:
  - name: Game Changer
    path: Game Changer
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        _dropout_root(
            str(tmp_path / "lib"),
            str(tmp_path / "old"),
            "  - shows/game-changer.yaml",
        ),
        encoding="utf-8",
    )
    body = client.get("/api/manifests/dropout").json()
    assert body["imports"][0]["path"] == "shows/game-changer.yaml"
    assert body["imports"][0]["exists"] is True
    assert "Game Changer" in body["imports"][0]["text"]


def test_put_dropout_import_writes_listed_path(tmp_path) -> None:
    client = _authed_client(tmp_path)
    (tmp_path / "shows").mkdir()
    (tmp_path / "dropout.yaml").write_text(
        _dropout_root(
            str(tmp_path / "lib"),
            str(tmp_path / "old"),
            "  - shows/game-changer.yaml",
        ),
        encoding="utf-8",
    )
    text = """
series:
  - name: Game Changer
    path: Game Changer
    url: https://watch.dropout.tv/game-changer
    seasons:
      - dropout: 1
"""
    response = client.put(
        "/api/manifests/dropout/imports",
        json={"path": "shows/game-changer.yaml", "text": text},
    )
    assert response.status_code == 200
    assert (tmp_path / "shows" / "game-changer.yaml").is_file()
    assert "Game Changer" in (tmp_path / "shows" / "game-changer.yaml").read_text(
        encoding="utf-8"
    )


def test_put_dropout_import_rejects_unlisted_path(tmp_path) -> None:
    client = _authed_client(tmp_path)
    (tmp_path / "dropout.yaml").write_text(
        _dropout_root(str(tmp_path / "lib"), str(tmp_path / "old")),
        encoding="utf-8",
    )
    response = client.put(
        "/api/manifests/dropout/imports",
        json={
            "path": "shows/game-changer.yaml",
            "text": "series:\n  - name: X\n    path: X\n    url: https://x\n    seasons:\n      - dropout: 1\n",
        },
    )
    assert response.status_code == 400


def test_put_dropout_import_rejects_escape(tmp_path) -> None:
    client = _authed_client(tmp_path)
    (tmp_path / "dropout.yaml").write_text(
        _dropout_root(
            str(tmp_path / "lib"),
            str(tmp_path / "old"),
            "  - shows/game-changer.yaml",
        ),
        encoding="utf-8",
    )
    response = client.put(
        "/api/manifests/dropout/imports",
        json={"path": "../secrets.yaml", "text": "series: []\n"},
    )
    assert response.status_code == 400


def test_get_dropout_omits_absolute_outside_data_dir(tmp_path) -> None:
    client = _authed_client(tmp_path)
    outside = tmp_path.parent / "outside-show.yaml"
    (tmp_path / "dropout.yaml").write_text(
        _dropout_root(
            str(tmp_path / "lib"),
            str(tmp_path / "old"),
            f"  - {outside}",
        ),
        encoding="utf-8",
    )
    body = client.get("/api/manifests/dropout").json()
    assert body["imports"] == []


def test_put_dropout_root_without_imports_still_works(tmp_path) -> None:
    client = _authed_client(tmp_path)
    text = _dropout_root(str(tmp_path / "lib"), str(tmp_path / "old"))
    response = client.put("/api/manifests/dropout", json={"text": text})
    assert response.status_code == 200
    assert response.json()["exists"] is True
