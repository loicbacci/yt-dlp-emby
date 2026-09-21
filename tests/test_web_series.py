import json
from pathlib import Path

import pytest
import yaml

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app

pytestmark = pytest.mark.web

NETSCAPE = "# Netscape HTTP Cookie File\n.watch.dropout.tv\tTRUE\t/\tTRUE\t0\t_session\tabc\n"


def _authed_ctx(tmp_path, environ=None) -> TestClient:
    """Client with custom environ; the caller must `with` it for lifespan exit."""
    client = TestClient(create_app(data_dir=tmp_path, environ=environ or {}))
    client.post("/api/setup", json={"password": "secretpass"})
    return client


def _write_cookies(tmp_path: Path, name: str = "dropout-cookies.txt") -> None:
    (tmp_path / name).write_text(NETSCAPE, encoding="utf-8")


def test_series_requires_auth(client) -> None:
    assert client.get("/api/series").status_code == 401
    assert (
        client.post(
            "/api/series", json={"name": "A", "platform": "dropout", "path": "A"}
        ).status_code
        == 401
    )


def test_list_and_create_series(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_list_does_not_merge_by_path(authed_client, tmp_path) -> None:
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
    client = authed_client
    names = [row["name"] for row in client.get("/api/series").json()["series"]]
    assert names == ["Alpha", "Beta"]


def test_get_prefers_import_over_inline(authed_client, tmp_path) -> None:
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
    client = authed_client
    body = client.get("/api/series/dropout/game-changer").json()
    assert body["inline"] is False
    assert body["path"] == "From Import"
    assert body["file"] == "shows/game-changer.yaml"


def test_dimension20_like_source_indexes(authed_client, tmp_path) -> None:
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
    client = authed_client
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


def test_put_season_display_title(authed_client, tmp_path) -> None:
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
    client = authed_client
    detail = client.get("/api/series/dropout/show").json()
    detail["sources"][0]["seasons"][0]["title"] = "Fantasy High Junior Year"
    saved = client.put("/api/series/dropout/show", json=detail).json()
    assert saved["sources"][0]["seasons"][0]["title"] == "Fantasy High Junior Year"
    assert saved["sources"][0]["seasons"][0]["label"] == "Fantasy High Junior Year"
    text = (shows / "show.yaml").read_text(encoding="utf-8")
    assert "Fantasy High Junior Year" in text


def test_put_remaps_and_delete_import(authed_client, tmp_path) -> None:
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
    client = authed_client
    detail = client.get("/api/series/dropout/show").json()
    detail["sources"][0]["seasons"][0]["remaps"] = [{"dropout_episode": 2, "skip": True}]
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


def test_put_does_not_infer_to_season(authed_client, tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "show.yaml").write_text(
        "series:\n  - name: Show\n    path: Show\n    url: https://watch.dropout.tv/x\n    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/show.yaml\nseries: []\n",
        encoding="utf-8",
    )
    client = authed_client
    detail = client.get("/api/series/dropout/show").json()
    assert detail["sources"][0]["seasons"][0]["to_season"] is None
    saved = client.put("/api/series/dropout/show", json=detail)
    assert saved.status_code == 200
    text = (shows / "show.yaml").read_text(encoding="utf-8")
    assert "to_season" not in text


def test_list_reports_broken_import(authed_client, tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "bad.yaml").write_text("series: not-a-list\n", encoding="utf-8")
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/bad.yaml\nseries: []\n",
        encoding="utf-8",
    )
    client = authed_client
    body = client.get("/api/series").json()
    assert body["series"] == []
    assert body["import_errors"]
    assert "bad.yaml" in body["import_errors"][0]["file"]


def test_yaml_save_preserves_root_comments(authed_client, tmp_path) -> None:
    (tmp_path / "dropout.yaml").write_text(
        "# keep this comment\nlibrary: /lib\nimports: []\nseries: []\n",
        encoding="utf-8",
    )
    client = authed_client
    created = client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show"},
    )
    assert created.status_code == 200
    text = (tmp_path / "dropout.yaml").read_text(encoding="utf-8")
    assert "# keep this comment" in text
    assert "library: /lib" in text


def test_inline_put_preserves_root_keys(authed_client, tmp_path) -> None:
    (tmp_path / "youtube.yaml").write_text(
        "library: /yt-lib\nold_dir: /old\ncookies: cookies.txt\n"
        "series:\n  - name: Example Channel\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLaaaa\n",
        encoding="utf-8",
    )
    client = authed_client
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


def test_add_source_to_inline_preserves_root(authed_client, tmp_path, monkeypatch) -> None:
    (tmp_path / "youtube.yaml").write_text(
        "library: /yt-lib\nseries:\n  - name: Example Channel\n    playlists: []\n",
        encoding="utf-8",
    )
    _write_cookies(tmp_path, "cookies.txt")
    client = authed_client

    def fake_discover(url, *, cookiefile=None, extract_channel=None):
        return [
            {
                "url": url,
                "seasons": [{"to_season": 1}],
            }
        ]

    monkeypatch.setattr("yt_dlp_emby.server.series.discover_youtube_sources", fake_discover)
    body = client.post(
        "/api/series/youtube/example-channel/sources",
        json={"url": "https://www.youtube.com/playlist?list=PLzzzz"},
    )
    assert body.status_code == 200
    root = yaml.safe_load((tmp_path / "youtube.yaml").read_text(encoding="utf-8"))
    assert root["library"] == "/yt-lib"
    assert len(root["series"][0]["playlists"]) == 1


def test_only_episodes_empty_toggle_400(authed_client, tmp_path) -> None:
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
    client = authed_client
    detail = client.get("/api/series/dropout/clip").json()
    assert detail["sources"][0]["seasons"][0]["only_episodes"] == [4]
    detail["sources"][0]["seasons"][0]["only_episodes"] = []
    resp = client.put("/api/series/dropout/clip", json=detail)
    assert resp.status_code == 400


def test_discover_missing_cookies_400(authed_client, tmp_path) -> None:
    client = authed_client
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
    assert "Cookies" in resp.json()["error"]


def test_discover_409_when_run_active(authed_client, tmp_path) -> None:
    client = authed_client
    created = client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show", "tvdb_id": None},
    )
    assert created.status_code == 200
    client.app.state.runner._state.status = "running"
    resp = client.post(
        "/api/series/dropout/show/sources",
        json={"url": "https://watch.dropout.tv/show"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"] == "a run is in progress"


def test_add_dropout_source_indexes(authed_client, tmp_path, monkeypatch) -> None:
    _write_cookies(tmp_path)
    client = authed_client
    client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show", "tvdb_id": None},
    )

    def fake_discover(url, *, cookiefile=None, fetch_html=None):
        return [
            {"dropout": 1, "url": url + "/season:1", "to_season": 1, "enabled": True},
            {"dropout": 2, "url": url + "/season:2", "to_season": 2, "enabled": True},
        ]

    monkeypatch.setattr("yt_dlp_emby.server.series.discover_dropout_source", fake_discover)
    body = client.post(
        "/api/series/dropout/show/sources",
        json={"url": "https://watch.dropout.tv/show"},
    ).json()
    assert body["sources"][0]["id"] == "0"
    assert [se["id"] for se in body["sources"][0]["seasons"]] == ["0", "1"]
    assert body["sources"][0]["seasons"][1]["dropout"] == 2


def test_put_rename_conflict_409(authed_client, tmp_path) -> None:
    client = authed_client
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


def test_create_rejects_escaping_shows_dir(authed_client, tmp_path) -> None:
    (tmp_path / "config.toml").write_text('shows_dir = "../outside"\n', encoding="utf-8")
    client = authed_client
    resp = client.post(
        "/api/series",
        json={"name": "Show", "platform": "dropout", "path": "Show", "tvdb_id": None},
    )
    assert resp.status_code == 400


def test_channel_extract_error_stays_on_source_card(authed_client, tmp_path, monkeypatch) -> None:
    (tmp_path / "youtube.yaml").write_text(
        "library: /yt-lib\nseries:\n  - name: Example Channel\n    playlists: []\n",
        encoding="utf-8",
    )
    _write_cookies(tmp_path, "cookies.txt")
    client = authed_client

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


def test_list_episodes_from_cache_includes_disk_status(authed_client, tmp_path) -> None:
    lib = tmp_path / "lib"
    dest = lib / "Clip" / "Season 1"
    dest.mkdir(parents=True)
    (dest / "Clip - S01E01 - Pilot.mkv").write_bytes(b"x")
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "clip.yaml").write_text(
        "series:\n  - name: Clip\n    path: Clip\n    url: https://watch.dropout.tv/c\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nimports:\n  - shows/clip.yaml\nseries: []\n",
        encoding="utf-8",
    )
    from yt_dlp_emby.cache import dropout_cache_path, save_dropout_season_cache

    save_dropout_season_cache(
        dropout_cache_path(tmp_path / "dropout.yaml"),
        {
            "https://watch.dropout.tv/c/season:1": [
                {
                    "url": "https://watch.dropout.tv/videos/pilot",
                    "title": "Pilot",
                    "dropout_episode": 1,
                },
                {
                    "url": "https://watch.dropout.tv/videos/two",
                    "title": "Two",
                    "dropout_episode": 2,
                },
            ]
        },
    )
    client = authed_client
    body = client.get("/api/series/dropout/clip/sources/0/seasons/0/episodes").json()
    by_id = {row["id"]: row for row in body["episodes"]}
    assert by_id["1"]["status"] == "downloaded"
    assert by_id["2"]["status"] == "missing"
    assert {"season": 1, "episode": 1} in body["on_disk"]
    disk = client.get("/api/series/dropout/clip/disk").json()
    assert {"season": 1, "episode": 1} in disk["on_disk"]
    listed = client.get("/api/series").json()["series"]
    assert listed[0]["missing_count"] == 1
    assert listed[0]["listings_complete"] is True


def test_list_missing_count_zero_when_complete(authed_client, tmp_path) -> None:
    lib = tmp_path / "lib"
    dest = lib / "Clip" / "Season 1"
    dest.mkdir(parents=True)
    (dest / "Clip - S01E01 - Pilot.mkv").write_bytes(b"x")
    (dest / "Clip - S01E02 - Two.mkv").write_bytes(b"x")
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "clip.yaml").write_text(
        "series:\n  - name: Clip\n    path: Clip\n    url: https://watch.dropout.tv/c\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nimports:\n  - shows/clip.yaml\nseries: []\n",
        encoding="utf-8",
    )
    from yt_dlp_emby.cache import dropout_cache_path, save_dropout_season_cache

    save_dropout_season_cache(
        dropout_cache_path(tmp_path / "dropout.yaml"),
        {
            "https://watch.dropout.tv/c/season:1": [
                {
                    "url": "https://watch.dropout.tv/videos/pilot",
                    "title": "Pilot",
                    "dropout_episode": 1,
                },
                {
                    "url": "https://watch.dropout.tv/videos/two",
                    "title": "Two",
                    "dropout_episode": 2,
                },
            ]
        },
    )
    client = authed_client
    listed = client.get("/api/series").json()["series"]
    assert listed[0]["missing_count"] == 0


def test_list_episodes_live_extract_writes_cache(authed_client, tmp_path, monkeypatch) -> None:
    from yt_dlp_emby.cache import dropout_cache_path, load_dropout_season_cache
    from yt_dlp_emby.extract import DropoutListing

    lib = tmp_path / "lib"
    lib.mkdir()
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "clip.yaml").write_text(
        "series:\n  - name: Clip\n    path: Clip\n    url: https://watch.dropout.tv/c\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nimports:\n  - shows/clip.yaml\nseries: []\n",
        encoding="utf-8",
    )
    _write_cookies(tmp_path)

    def fake_extract(url, **_kwargs):
        assert url == "https://watch.dropout.tv/c/season:1"
        return [
            DropoutListing(
                url="https://watch.dropout.tv/videos/pilot",
                title="Pilot",
                dropout_episode=1,
            )
        ]

    monkeypatch.setattr("yt_dlp_emby.server.series.extract_dropout_season", fake_extract)
    client = authed_client
    body = client.get("/api/series/dropout/clip/sources/0/seasons/0/episodes")
    assert body.status_code == 200
    cached = load_dropout_season_cache(dropout_cache_path(tmp_path / "dropout.yaml"))
    assert cached["https://watch.dropout.tv/c/season:1"][0]["title"] == "Pilot"
    listed = client.get("/api/series").json()["series"]
    assert listed[0]["missing_count"] == 1


def test_missing_endpoint_hydrates_uncached_seasons(authed_client, tmp_path, monkeypatch) -> None:
    from yt_dlp_emby.cache import dropout_cache_path, load_dropout_season_cache
    from yt_dlp_emby.extract import DropoutListing

    lib = tmp_path / "lib"
    lib.mkdir()
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "clip.yaml").write_text(
        "series:\n  - name: Clip\n    path: Clip\n    url: https://watch.dropout.tv/c\n"
        "    seasons:\n      - dropout: 1\n      - dropout: 2\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nimports:\n  - shows/clip.yaml\nseries: []\n",
        encoding="utf-8",
    )
    _write_cookies(tmp_path)
    fetched: list[str] = []

    def fake_extract(url, **_kwargs):
        fetched.append(url)
        season = 1 if "season:1" in url else 2
        return [
            DropoutListing(
                url=f"https://watch.dropout.tv/videos/s{season}",
                title=f"Ep {season}",
                dropout_episode=1,
            )
        ]

    monkeypatch.setattr("yt_dlp_emby.server.series.extract_dropout_season", fake_extract)
    client = authed_client
    listed = client.get("/api/series").json()["series"]
    assert listed[0]["missing_count"] is None
    assert listed[0]["listings_complete"] is False
    body = client.get("/api/series/dropout/clip/missing")
    assert body.status_code == 200, body.text
    payload = body.json()
    assert payload["complete"] is True
    assert payload["missing_count"] == 2
    assert fetched == [
        "https://watch.dropout.tv/c/season:1",
        "https://watch.dropout.tv/c/season:2",
    ]
    cached = load_dropout_season_cache(dropout_cache_path(tmp_path / "dropout.yaml"))
    assert "https://watch.dropout.tv/c/season:1" in cached
    again = client.get("/api/series/dropout/clip/missing").json()
    assert again["missing_count"] == 2
    assert fetched == [
        "https://watch.dropout.tv/c/season:1",
        "https://watch.dropout.tv/c/season:2",
    ]


def test_check_uses_file_stem_when_name_has_apostrophe(tmp_path) -> None:
    lib = tmp_path / "lib"
    lib.mkdir()
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
    ffmpeg.chmod(0o755)
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "dimension-20-adventuring-party.yaml").write_text(
        "series:\n"
        "  - name: Dimension 20's Adventuring Party\n"
        "    path: AP\n"
        "    tvdb_id: 391568\n"
        "    url: https://watch.dropout.tv/ap\n"
        "    seasons:\n"
        "      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\n"
        "imports:\n  - shows/dimension-20-adventuring-party.yaml\nseries: []\n",
        encoding="utf-8",
    )
    from yt_dlp_emby.cache import dropout_cache_path, save_dropout_season_cache
    from yt_dlp_emby.sonarr import save_sonarr_cache, sonarr_cache_path

    save_dropout_season_cache(
        dropout_cache_path(tmp_path / "dropout.yaml"),
        {
            "https://watch.dropout.tv/ap/season:1": [
                {
                    "url": "https://watch.dropout.tv/videos/pilot",
                    "title": "Pilot",
                    "dropout_episode": 1,
                }
            ]
        },
    )
    save_sonarr_cache(
        sonarr_cache_path(tmp_path / "dropout.yaml"),
        {
            "391568": {
                "title": "Dimension 20's Adventuring Party",
                "episodes": [{"season": 1, "episode": 1, "title": "Pilot"}],
            }
        },
    )
    client = _authed_ctx(
        tmp_path,
        environ={
            "YT_DLP_EMBY_SONARR_URL": "http://sonarr.example",
            "YT_DLP_EMBY_SONARR_API_KEY": "k",
            "YT_DLP_EMBY_FFMPEG": str(ffmpeg),
        },
    )
    with client:
        listed = client.get("/api/series").json()["series"]
        assert listed[0]["slug"] == "dimension-20-adventuring-party"
        check = client.get("/api/series/dropout/dimension-20-adventuring-party/check")
        assert check.status_code == 200, check.text
        assert check.json()["ok"] is True
        layout = client.get("/api/series/dropout/dimension-20-adventuring-party/layout")
        assert layout.status_code == 200, layout.text


def test_series_list_includes_poster_url(authed_client, tmp_path) -> None:
    client = authed_client
    client.post(
        "/api/series",
        json={
            "name": "Game Changer",
            "platform": "dropout",
            "path": "Game Changer [tvdbid=1]",
            "tvdb_id": 1,
        },
    )
    listed = client.get("/api/series").json()["series"]
    assert listed[0]["poster_url"] == "/api/series/dropout/game-changer/poster"


def test_poster_requires_auth(client) -> None:
    assert client.get("/api/series/dropout/x/poster").status_code == 401


def test_poster_404_without_art(authed_client, tmp_path) -> None:
    client = authed_client
    client.post(
        "/api/series",
        json={"name": "Solo", "platform": "dropout", "path": "Solo"},
    )
    assert client.get("/api/series/dropout/solo/poster").status_code == 404


def test_refresh_requires_auth(client) -> None:
    assert (
        client.post(
            "/api/series/refresh?sync=1",
            json={"items": [{"platform": "dropout", "slug": "solo"}]},
        ).status_code
        == 401
    )


def test_refresh_empty_items_400(authed_client, tmp_path) -> None:
    client = authed_client
    assert client.post("/api/series/refresh?sync=1", json={"items": []}).status_code == 400


def test_poster_returns_library_file(tmp_path) -> None:
    lib = tmp_path / "lib"
    show_dir = lib / "Solo"
    show_dir.mkdir(parents=True)
    (show_dir / "poster.jpg").write_bytes(b"\xff\xd8\xff\xd9")
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nseries: []\n",
        encoding="utf-8",
    )
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
    client = _authed_ctx(tmp_path, environ={"YT_DLP_EMBY_FFMPEG": str(ffmpeg)})
    with client:
        created = client.post(
            "/api/series",
            json={"name": "Solo", "platform": "dropout", "path": "Solo"},
        )
        assert created.status_code == 200, created.text
        response = client.get("/api/series/dropout/solo/poster")
        assert response.status_code == 200
        assert response.content.startswith(b"\xff\xd8")


def test_refresh_dropout_force_listing(authed_client, tmp_path, monkeypatch) -> None:
    from yt_dlp_emby.cache import (
        dropout_cache_path,
        dropout_listings_to_cache,
        load_dropout_season_cache,
        save_dropout_season_cache,
    )
    from yt_dlp_emby.extract import DropoutListing

    lib = tmp_path / "lib"
    lib.mkdir()
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "clip.yaml").write_text(
        "series:\n  - name: Clip\n    path: Clip\n    url: https://watch.dropout.tv/c\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nimports:\n  - shows/clip.yaml\nseries: []\n",
        encoding="utf-8",
    )
    _write_cookies(tmp_path)
    page = "https://watch.dropout.tv/c/season:1"
    save_dropout_season_cache(
        dropout_cache_path(tmp_path / "dropout.yaml"),
        {
            page: dropout_listings_to_cache(
                [
                    DropoutListing(
                        url="https://watch.dropout.tv/videos/old",
                        title="Old Pilot",
                        dropout_episode=1,
                    )
                ]
            )
        },
    )
    fetched: list[str] = []

    def fake_extract(url, **_kwargs):
        fetched.append(url)
        return [
            DropoutListing(
                url="https://watch.dropout.tv/videos/pilot",
                title="New Pilot",
                dropout_episode=1,
            )
        ]

    monkeypatch.setattr("yt_dlp_emby.server.series.extract_dropout_season", fake_extract)
    client = authed_client
    response = client.post(
        "/api/series/refresh?sync=1",
        json={"items": [{"platform": "dropout", "slug": "clip"}]},
    )
    assert response.status_code == 200, response.text
    assert fetched == [page]
    cached = load_dropout_season_cache(dropout_cache_path(tmp_path / "dropout.yaml"))
    assert cached[page][0]["title"] == "New Pilot"


def _seed_two_show_plan(tmp_path: Path) -> None:
    (tmp_path / "plan.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00",
                "force": False,
                "sources": {
                    "dropout": {
                        "ok": True,
                        "error": None,
                        "seasons": [
                            {"slug": "show", "dest_season": 1, "download": 1},
                            {"slug": "other", "dest_season": 2, "download": 1},
                        ],
                        "items": [
                            {
                                "slug": "show",
                                "id": "dropout|show|S01E01",
                                "action": "download",
                            },
                            {
                                "slug": "other",
                                "id": "dropout|other|S02E01",
                                "action": "download",
                            },
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )


def _patch_only_requested_slug(monkeypatch) -> list[tuple[str, str]]:
    from yt_dlp_emby.events import merge_plan_slug
    from yt_dlp_emby.server.plan_series import plan_path

    patched: list[tuple[str, str]] = []

    def fake_patch(data_dir, platform, slug, *, environ, force_refetch=False):
        patched.append((platform, slug))
        merge_plan_slug(
            plan_path(data_dir),
            platform,
            slug,
            {"ok": True, "error": None, "seasons": [], "items": []},
        )

    monkeypatch.setattr("yt_dlp_emby.server.plan_series.patch_series_plan", fake_patch)
    return patched


def test_disk_refresh_patches_only_that_slug(authed_client, tmp_path, monkeypatch) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "show.yaml").write_text(
        "series:\n  - name: Show\n    path: Show\n    url: https://watch.dropout.tv/x\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/show.yaml\nseries: []\n",
        encoding="utf-8",
    )
    _seed_two_show_plan(tmp_path)
    patched = _patch_only_requested_slug(monkeypatch)
    client = authed_client
    response = client.post(
        "/api/series/refresh?sync=1",
        json={
            "items": [{"platform": "dropout", "slug": "show"}],
            "parts": ["disk"],
        },
    )
    assert response.status_code == 200, response.text
    assert patched == [("dropout", "show")]
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    items = plan["sources"]["dropout"]["items"]
    assert [row["id"] for row in items] == ["dropout|other|S02E01"]


def test_sonarr_refresh_does_not_patch_plan(authed_client, tmp_path, monkeypatch) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "show.yaml").write_text(
        "series:\n  - name: Show\n    path: Show\n    tvdb_id: 9\n"
        "    url: https://watch.dropout.tv/x\n    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/show.yaml\nseries: []\n",
        encoding="utf-8",
    )
    _seed_two_show_plan(tmp_path)
    patched = _patch_only_requested_slug(monkeypatch)
    client = authed_client
    response = client.post(
        "/api/series/refresh?sync=1",
        json={
            "items": [{"platform": "dropout", "slug": "show"}],
            "parts": ["sonarr"],
        },
    )
    assert response.status_code == 200, response.text
    assert patched == []
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in plan["sources"]["dropout"]["items"]] == [
        "dropout|show|S01E01",
        "dropout|other|S02E01",
    ]


def test_put_skip_patches_that_slug_plan_items(authed_client, tmp_path, monkeypatch) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "show.yaml").write_text(
        "series:\n  - name: Show\n    path: Show\n    url: https://watch.dropout.tv/x\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports:\n  - shows/show.yaml\nseries: []\n",
        encoding="utf-8",
    )
    _seed_two_show_plan(tmp_path)
    patched = _patch_only_requested_slug(monkeypatch)
    client = authed_client
    detail = client.get("/api/series/dropout/show").json()
    detail["sources"][0]["seasons"][0]["remaps"] = [{"dropout_episode": 1, "skip": True}]
    saved = client.put("/api/series/dropout/show", json=detail)
    assert saved.status_code == 200, saved.text
    assert patched == [("dropout", "show")]
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    assert [row["id"] for row in plan["sources"]["dropout"]["items"]] == ["dropout|other|S02E01"]


def test_series_yaml_roundtrip(authed_client, tmp_path) -> None:
    client = authed_client
    created = client.post(
        "/api/series",
        json={
            "name": "Game Changer",
            "platform": "dropout",
            "path": "Game Changer",
            "tvdb_id": 1,
        },
    )
    assert created.status_code == 200, created.text
    got = client.get("/api/series/dropout/game-changer/yaml")
    assert got.status_code == 200, got.text
    body = got.json()
    assert "Game Changer" in body["text"]
    assert body["file"]
    saved = client.put(
        "/api/series/dropout/game-changer/yaml",
        json={"text": "name: Crowd Control\npath: Crowd Control\ntvdb_id: 1\n"},
    )
    assert saved.status_code == 200, saved.text
    assert saved.json()["name"] == "Crowd Control"
    assert saved.json()["path"] == "Crowd Control"
    reloaded = client.get("/api/series/dropout/game-changer").json()
    assert reloaded["name"] == "Crowd Control"
    bad = client.put(
        "/api/series/dropout/game-changer/yaml",
        json={"text": "name: [\n"},
    )
    assert bad.status_code == 400


def test_poster_sonarr_config_error_is_404(authed_client, tmp_path, monkeypatch) -> None:
    from yt_dlp_emby.config import ConfigError

    def boom(*_args, **_kwargs):
        raise ConfigError("URL resolves to a private or reserved address")

    monkeypatch.setattr("yt_dlp_emby.sonarr.fetch_sonarr_poster", boom)
    client = authed_client
    created = client.post(
        "/api/series",
        json={"name": "Solo", "platform": "dropout", "path": "Solo", "tvdb_id": 99},
    )
    assert created.status_code == 200, created.text
    (tmp_path / "config.toml").write_text(
        'sonarr_url = "http://192.168.1.10:8989"\nsonarr_api_key = "secret"\n',
        encoding="utf-8",
    )
    response = client.get("/api/series/dropout/solo/poster")
    assert response.status_code == 404


def test_plans_latest_drops_episodes_already_on_disk(authed_client, tmp_path) -> None:
    lib = tmp_path / "lib"
    dest = lib / "Clip" / "Season 1"
    dest.mkdir(parents=True)
    (dest / "Clip - S01E01 - Pilot.mkv").write_bytes(b"x")
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "clip.yaml").write_text(
        "series:\n  - name: Clip\n    path: Clip\n    url: https://watch.dropout.tv/c\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )
    (tmp_path / "dropout.yaml").write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\nimports:\n  - shows/clip.yaml\nseries: []\n",
        encoding="utf-8",
    )
    from yt_dlp_emby.cache import dropout_cache_path, save_dropout_season_cache

    save_dropout_season_cache(
        dropout_cache_path(tmp_path / "dropout.yaml"),
        {
            "https://watch.dropout.tv/c/season:1": [
                {
                    "url": "https://watch.dropout.tv/videos/pilot",
                    "title": "Pilot",
                    "dropout_episode": 1,
                },
                {
                    "url": "https://watch.dropout.tv/videos/two",
                    "title": "Two",
                    "dropout_episode": 2,
                },
            ]
        },
    )
    (tmp_path / "plan.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00",
                "force": False,
                "sources": {
                    "dropout": {
                        "ok": True,
                        "error": None,
                        "seasons": [
                            {
                                "slug": "clip",
                                "dest_season": 1,
                                "download": 2,
                                "skip": 0,
                                "replace": 0,
                                "unmapped": 0,
                                "folder": "Season 1",
                                "season_title": None,
                                "series": "Clip",
                            }
                        ],
                        "items": [
                            {
                                "slug": "clip",
                                "id": "dropout|clip|S01E01",
                                "action": "download",
                                "code": "S01E01",
                                "title": "Pilot",
                                "dest_season": 1,
                                "series": "Clip",
                                "platform": "dropout",
                            },
                            {
                                "slug": "clip",
                                "id": "dropout|clip|S01E02",
                                "action": "download",
                                "code": "S01E02",
                                "title": "Two",
                                "dest_season": 1,
                                "series": "Clip",
                                "platform": "dropout",
                            },
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    client = authed_client
    plan = client.get("/api/plans/latest").json()
    assert [row["id"] for row in plan["sources"]["dropout"]["items"]] == ["dropout|clip|S01E02"]
    listed = client.get("/api/series").json()["series"]
    assert listed[0]["missing_count"] == 1
    snapshot = client.get("/api/runs").json()
    assert snapshot["plan"]["pending"] == 1
