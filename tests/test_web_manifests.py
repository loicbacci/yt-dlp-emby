import pytest

pytest.importorskip("fastapi")

from yt_dlp_emby.server.manifests import read_manifest

pytestmark = pytest.mark.web


def test_get_missing_returns_example(authed_client, tmp_path) -> None:
    client = authed_client
    response = client.get("/api/manifests/youtube")
    assert response.status_code == 200
    body = response.json()
    assert body["exists"] is False
    assert "Example Channel" in body["text"]
    assert not (tmp_path / "youtube.yaml").exists()


def test_put_creates_and_validates(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_put_rejects_invalid_without_writing(authed_client, tmp_path) -> None:
    client = authed_client
    bad = "library: /lib\nold_dir: /old\nseries: []\n"
    response = client.put("/api/manifests/youtube", json={"text": bad})
    assert response.status_code == 400
    assert "series" in response.json()["error"].lower()
    assert not (tmp_path / "youtube.yaml").exists()


def test_put_keeps_previous_file_when_invalid(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_validate_rejects_invalid_yaml_syntax(authed_client, tmp_path) -> None:
    client = authed_client
    response = client.post(
        "/api/manifests/youtube/validate",
        json={"text": "library: [\n"},
    )
    assert response.status_code == 400
    assert "invalid yaml" in response.json()["error"].lower()


def test_validate_rejects_schema(authed_client, tmp_path) -> None:
    client = authed_client
    response = client.post(
        "/api/manifests/youtube/validate",
        json={"text": "library: /lib\nold_dir: /old\nseries: []\n"},
    )
    assert response.status_code == 400
    assert "series" in response.json()["error"].lower()


def test_validate_accepts_valid_manifest(authed_client, tmp_path) -> None:
    client = authed_client
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
    body = response.json()
    assert body["ok"] is True
    assert body["paths"]["library"]["source"] == "manifest"
    assert not (tmp_path / "youtube.yaml").exists()


def test_validate_dropout_schema(authed_client, tmp_path) -> None:
    client = authed_client
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
    assert "url" in response.json()["error"].lower()


def test_unknown_kind_404(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_get_dropout_imports_empty_without_key(authed_client, tmp_path) -> None:
    client = authed_client
    (tmp_path / "dropout.yaml").write_text(
        _dropout_root(str(tmp_path / "lib"), str(tmp_path / "old")),
        encoding="utf-8",
    )
    body = client.get("/api/manifests/dropout").json()
    assert body["imports"] == []


def test_get_dropout_lists_relative_import(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_put_dropout_import_writes_listed_path(authed_client, tmp_path) -> None:
    client = authed_client
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
    assert "Game Changer" in (tmp_path / "shows" / "game-changer.yaml").read_text(encoding="utf-8")


def test_put_dropout_import_rejects_unlisted_path(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_put_dropout_import_rejects_escape(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_get_dropout_omits_absolute_outside_data_dir(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_put_dropout_root_without_imports_still_works(authed_client, tmp_path) -> None:
    client = authed_client
    text = _dropout_root(str(tmp_path / "lib"), str(tmp_path / "old"))
    response = client.put("/api/manifests/dropout", json={"text": text})
    assert response.status_code == 200
    assert response.json()["exists"] is True


def _listed_dropout_root(tmp_path, *listed: str) -> None:
    imports = "".join(f"  - {item}\n" for item in listed)
    (tmp_path / "dropout.yaml").write_text(
        _dropout_root(str(tmp_path / "lib"), str(tmp_path / "old"), imports),
        encoding="utf-8",
    )


_VALID_IMPORT_TEXT = (
    "series:\n  - name: Game Changer\n    path: Game Changer\n"
    "    url: https://watch.dropout.tv/game-changer\n    seasons:\n      - dropout: 1\n"
)


@pytest.mark.parametrize("evil", ["../x", "../secrets.yaml", "/etc/passwd"])
def test_put_import_rejects_listed_escape(authed_client, tmp_path, evil: str) -> None:
    """A listed-but-escaping import path must 400, never read/write outside."""
    client = authed_client
    _listed_dropout_root(tmp_path, "shows/game-changer.yaml", evil)
    response = client.put(
        "/api/manifests/dropout/imports",
        json={"path": evil, "text": _VALID_IMPORT_TEXT},
    )
    assert response.status_code == 400
    body = client.get("/api/manifests/dropout").json()
    assert all(item["path"] != evil for item in body["imports"])


def test_import_symlink_to_etc_is_confined(authed_client, tmp_path) -> None:
    """A listed import that symlinks outside the data dir is omitted/rejected."""
    client = authed_client
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "evil.yaml").symlink_to("/etc/passwd")
    _listed_dropout_root(tmp_path, "shows/evil.yaml")
    body = client.get("/api/manifests/dropout").json()
    assert body["imports"] == []
    response = client.put(
        "/api/manifests/dropout/imports",
        json={"path": "shows/evil.yaml", "text": _VALID_IMPORT_TEXT},
    )
    assert response.status_code == 400


def test_cookies_yaml_traversal_falls_back_to_default_jar(authed_client, tmp_path) -> None:
    """cookies: ../../evil in yaml must not escape on cookie save."""
    client = authed_client
    (tmp_path / "youtube.yaml").write_text(
        'library: "/lib"\ncookies: "../../evil"\nseries: []\n',
        encoding="utf-8",
    )
    netscape = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tSID\tabc\n"
    response = client.put("/api/cookies/youtube", json={"text": netscape})
    assert response.status_code == 200
    assert (tmp_path / "cookies.txt").is_file()
    assert not (tmp_path.parent / "evil").exists()


@pytest.mark.parametrize("evil", ["../../evil", "/etc/passwd", "../cookies.txt"])
def test_put_platform_cookies_rejects_traversal(authed_client, tmp_path, evil: str) -> None:
    """put_platform.cookies must reject .. and absolute/system paths (400)."""
    client = authed_client
    (tmp_path / "youtube.yaml").write_text(
        'library: "/lib"\nseries: []\n',
        encoding="utf-8",
    )
    response = client.put("/api/platform/youtube", json={"cookies": evil})
    assert response.status_code == 400, response.text


def test_assets_rejects_encoded_traversal(authed_client, tmp_path) -> None:
    client = authed_client
    response = client.get("/assets/..%2f..%2findex.html")
    assert response.status_code == 404


def test_get_youtube_lists_relative_import(authed_client, tmp_path) -> None:
    client = authed_client
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "example.yaml").write_text(
        "series:\n  - name: Example Channel\n    playlists: []\n",
        encoding="utf-8",
    )
    (tmp_path / "youtube.yaml").write_text(
        "library: /lib\nold_dir: /old\nimports:\n  - shows/example.yaml\nseries: []\n",
        encoding="utf-8",
    )
    body = client.get("/api/manifests/youtube").json()
    assert body["imports"][0]["path"] == "shows/example.yaml"
    assert body["imports"][0]["exists"] is True
    assert "Example Channel" in body["imports"][0]["text"]
