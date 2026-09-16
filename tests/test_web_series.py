import pytest
import yaml
from pathlib import Path

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app

pytestmark = pytest.mark.web

NETSCAPE = (
    "# Netscape HTTP Cookie File\n"
    ".watch.dropout.tv\tTRUE\t/\tTRUE\t0\t_session\tabc\n"
)


def _authed(tmp_path, environ=None) -> TestClient:
    client = TestClient(create_app(data_dir=tmp_path, environ=environ or {}))
    client.post("/api/setup", json={"password": "secretpass"})
    return client


def _write_cookies(tmp_path: Path, name: str = "dropout-cookies.txt") -> None:
    (tmp_path / name).write_text(NETSCAPE, encoding="utf-8")


def test_series_requires_auth(tmp_path) -> None:
    client = TestClient(create_app(data_dir=tmp_path, environ={}))
    assert client.get("/api/series").status_code == 401
    assert client.post("/api/series", json={"name": "A", "platform": "dropout", "path": "A"}).status_code == 401


def test_list_and_create_series(tmp_path) -> None:
    client = _authed(tmp_path)
    assert client.get("/api/series").json()["series"] == []
    response = client.post(
        "/api/series",
        json={
            "name": "Game Changer",
            "platform": "dropout",
            "path": "Game Changer [tvdbid=1]",
            "tvdb_id": 1,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["slug"] == "game-changer"
    assert body["source_count"] == 0
    listed = client.get("/api/series").json()["series"]
    assert len(listed) == 1
    dup = client.post(
        "/api/series",
        json={"name": "Game Changer", "platform": "youtube", "path": "X"},
    )
    assert dup.status_code == 409
    invalid = client.post(
        "/api/series",
        json={"name": "---", "platform": "dropout", "path": "Nope"},
    )
    assert invalid.status_code == 400


def test_list_does_not_merge_by_path(tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "a.yaml").write_text(
        "series:\n  - name: Alpha\n    path: Shared\n",
        encoding="utf-8",
    )
    (shows / "b.yaml").write_text(
        "series:\n  - name: Beta\n    path: Shared\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/a.yaml\n  - shows/b.yaml\nseries: []\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    names = [row["name"] for row in client.get("/api/series").json()["series"]]
    assert names == ["Alpha", "Beta"]


def test_get_prefers_import_over_inline(tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "game-changer.yaml").write_text(
        "series:\n  - name: Game Changer\n    path: From Import\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "library: /lib\nimports:\n  - shows/game-changer.yaml\n"
        "series:\n  - name: Game Changer\n    path: From Inline\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    body = client.get("/api/series/dropout/game-changer").json()
    assert body["inline"] is False
    assert body["path"] == "From Import"
    assert body["file"] == "shows/game-changer.yaml"


def test_dimension20_like_source_indexes(tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "dimension-20.yaml").write_text(
        """
series:
  - name: Dimension 20
    path: Dimension 20 [tvdbid=354216]
    tvdb_id: 354216
    urls:
      - url: https://watch.dropout.tv/one
        seasons:
          - dropout: 1
            remap:
              - dropout_episode: 3
                to_season: 1
                to_episode: 3
      - url: https://watch.dropout.tv/two
        seasons:
          - dropout: 1
            to_season: 0
""".strip()
        + "\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/dimension-20.yaml\nseries: []\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    body = client.get("/api/series/dropout/dimension-20").json()
    assert len(body["sources"]) == 2
    assert body["sources"][0]["id"] == "0"
    assert body["sources"][1]["id"] == "1"
    assert body["sources"][0]["seasons"][0]["id"] == "0"
    assert body["sources"][0]["seasons"][0]["dropout"] == 1
    assert body["sources"][1]["seasons"][0]["to_season"] == 0
    remap = body["sources"][0]["seasons"][0]["remaps"][0]
    assert remap["dropout_episode"] == 3
    assert remap["to_season"] == 1


def test_put_season_display_title(tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "show.yaml").write_text(
        "series:\n  - name: Show\n    path: Show\n    url: https://watch.dropout.tv/x\n    seasons:\n      - dropout: 1\n        to_season: 21\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/show.yaml\nseries: []\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    detail = client.get("/api/series/dropout/show").json()
    detail["sources"][0]["seasons"][0]["title"] = "Fantasy High Junior Year"
    saved = client.put("/api/series/dropout/show", json=detail).json()
    assert saved["sources"][0]["seasons"][0]["title"] == "Fantasy High Junior Year"
    assert saved["sources"][0]["seasons"][0]["label"] == "Fantasy High Junior Year"
    text = (shows / "show.yaml").read_text(encoding="utf-8")
    assert "Fantasy High Junior Year" in text


def test_put_remaps_and_delete_import(tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "show.yaml").write_text(
        "series:\n  - name: Show\n    path: Show\n    url: https://watch.dropout.tv/x\n    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "library: /keep\nimports:\n  - shows/show.yaml\nseries: []\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    detail = client.get("/api/series/dropout/show").json()
    detail["sources"][0]["seasons"][0]["remaps"] = [
        {"dropout_episode": 2, "skip": True}
    ]
    saved = client.put("/api/series/dropout/show", json=detail)
    assert saved.status_code == 200
    text = (shows / "show.yaml").read_text(encoding="utf-8")
    assert "dropout_episode: 2" in text
    deleted = client.delete("/api/series/dropout/show")
    assert deleted.status_code == 204
    assert not (shows / "show.yaml").exists()
    root = (tmp_path / "dropout.yaml").read_text(encoding="utf-8")
    assert "shows/show.yaml" not in root
    assert "/keep" in root


def test_inline_put_preserves_root_keys(tmp_path) -> None:
    (tmp_path / "youtube.yaml").write_text(
        "library: /yt-lib\nold_dir: /old\ncookies: cookies.txt\n"
        "series:\n  - name: Example Channel\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLaaaa\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    detail = client.get("/api/series/youtube/example-channel").json()
    assert detail["inline"] is True
    detail["path"] = "Example Channel Folder"
    saved = client.put("/api/series/youtube/example-channel", json=detail)
    assert saved.status_code == 200
    root = yaml.safe_load((tmp_path / "youtube.yaml").read_text(encoding="utf-8"))
    assert root["library"] == "/yt-lib"
    assert root["old_dir"] == "/old"
    assert root["cookies"] == "cookies.txt"
    assert root["series"][0]["path"] == "Example Channel Folder"


def test_add_source_to_inline_preserves_root(tmp_path, monkeypatch) -> None:
    (tmp_path / "youtube.yaml").write_text(
        "library: /yt-lib\nseries:\n  - name: Example Channel\n    playlists: []\n",
        encoding="utf-8",
    )
    _write_cookies(tmp_path, "cookies.txt")
    client = _authed(tmp_path)

    def fake_discover(url, *, cookiefile=None, extract_channel=None):
        return [
            {
                "url": url,
                "seasons": [{"to_season": 1}],
            }
        ]

    monkeypatch.setattr(
        "yt_dlp_emby.server.series.discover_youtube_sources", fake_discover
    )
    body = client.post(
        "/api/series/youtube/example-channel/sources",
        json={"url": "https://www.youtube.com/playlist?list=PLzzzz"},
    )
    assert body.status_code == 200
    root = yaml.safe_load((tmp_path / "youtube.yaml").read_text(encoding="utf-8"))
    assert root["library"] == "/yt-lib"
    assert len(root["series"][0]["playlists"]) == 1


def test_only_episodes_empty_toggle_400(tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "clip.yaml").write_text(
        "series:\n  - name: Clip\n    path: Clip\n    url: https://watch.dropout.tv/c\n"
        "    seasons:\n      - dropout: 1\n        only_episodes: [4]\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/clip.yaml\nseries: []\n",
        encoding="utf-8",
    )
    client = _authed(tmp_path)
    detail = client.get("/api/series/dropout/clip").json()
    assert detail["sources"][0]["seasons"][0]["only_episodes"] == [4]
    detail["sources"][0]["seasons"][0]["only_episodes"] = []
    resp = client.put("/api/series/dropout/clip", json=detail)
    assert resp.status_code == 400


def test_discover_missing_cookies_400(tmp_path) -> None:
    client = _authed(tmp_path)
    created = client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show", "tvdb_id": None},
    )
    assert created.status_code == 200
    resp = client.post(
        "/api/series/dropout/show/sources",
        json={"url": "https://watch.dropout.tv/show"},
    )
    assert resp.status_code == 400
    assert "Cookies" in resp.json()["detail"]["error"]


def test_discover_409_when_run_active(tmp_path) -> None:
    client = _authed(tmp_path)
    created = client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show", "tvdb_id": None},
    )
    assert created.status_code == 200
    client.app.state.runner.snapshot = lambda: {"status": "running"}
    resp = client.post(
        "/api/series/dropout/show/sources",
        json={"url": "https://watch.dropout.tv/show"},
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["error"] == "a run is in progress"


def test_add_dropout_source_indexes(tmp_path, monkeypatch) -> None:
    _write_cookies(tmp_path)
    client = _authed(tmp_path)
    client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show", "tvdb_id": None},
    )

    def fake_discover(url, *, cookiefile=None, fetch_html=None):
        return [
            {"dropout": 1, "url": url + "/season:1", "to_season": 1, "enabled": True},
            {"dropout": 2, "url": url + "/season:2", "to_season": 2, "enabled": True},
        ]

    monkeypatch.setattr(
        "yt_dlp_emby.server.series.discover_dropout_source", fake_discover
    )
    body = client.post(
        "/api/series/dropout/show/sources",
        json={"url": "https://watch.dropout.tv/show"},
    ).json()
    assert body["sources"][0]["id"] == "0"
    assert [se["id"] for se in body["sources"][0]["seasons"]] == ["0", "1"]
    assert body["sources"][0]["seasons"][1]["dropout"] == 2


def test_put_rename_conflict_409(tmp_path) -> None:
    client = _authed(tmp_path)
    assert (
        client.post(
            "/api/series",
            json={"name": "Game Changer", "platform": "dropout", "path": "GC", "tvdb_id": None},
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/series",
            json={"name": "Dimension 20", "platform": "dropout", "path": "D20", "tvdb_id": None},
        ).status_code
        == 200
    )
    detail = client.get("/api/series/dropout/game-changer").json()
    detail["name"] = "Dimension 20"
    resp = client.put("/api/series/dropout/game-changer", json=detail)
    assert resp.status_code == 409


def test_create_rejects_escaping_shows_dir(tmp_path) -> None:
    (tmp_path / "config.toml").write_text('shows_dir = "../outside"\n', encoding="utf-8")
    client = _authed(tmp_path)
    resp = client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show", "tvdb_id": None},
    )
    assert resp.status_code == 400


def test_channel_extract_error_stays_on_source_card(tmp_path, monkeypatch) -> None:
    (tmp_path / "youtube.yaml").write_text(
        "library: /yt-lib\nseries:\n  - name: Example Channel\n    playlists: []\n",
        encoding="utf-8",
    )
    _write_cookies(tmp_path, "cookies.txt")
    client = _authed(tmp_path)

    def boom(url, *, cookiefile=None, extract_channel=None):
        from yt_dlp_emby.server.series_discover import ChannelDiscoverError

        raise ChannelDiscoverError(url, "login required")

    monkeypatch.setattr("yt_dlp_emby.server.series.discover_youtube_sources", boom)
    body = client.post(
        "/api/series/youtube/example-channel/sources",
        json={"url": "https://www.youtube.com/@example"},
    )
    assert body.status_code == 200
    source = body.json()["sources"][-1]
    assert source["url"] == "https://www.youtube.com/@example"
    assert source["error"] == "login required"
