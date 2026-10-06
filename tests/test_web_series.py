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


def test_discover_409_when_job_active(authed_client, tmp_path) -> None:
    client = authed_client
    assert (
        client.post(
            "/api/series", json={"name": "Show", "platform": "dropout", "path": "Show"}
        ).status_code
        == 200
    )
    client.app.state.job_store.create("active-job", "refresh", {"kind": "refresh", "items": []})
    response = client.post(
        "/api/series/dropout/show/sources", json={"url": "https://watch.dropout.tv/show"}
    )
    assert response.status_code == 409
    assert response.json()["code"] == "JOB_CONFLICT"


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


def test_list_episodes_from_cached_view_includes_disk_status(authed_client, tmp_path) -> None:
    _configured_shows(tmp_path, ["Clip"])
    _cache_view(authed_client, tmp_path, "clip", on_disk=[(1, 1)])
    body = authed_client.get("/api/series/dropout/clip/sources/0/seasons/0/episodes").json()
    by_id = {row["id"]: row for row in body["episodes"]}
    assert by_id["1"]["status"] == "downloaded"
    assert by_id["2"]["status"] == "missing"
    assert body["on_disk"] == [{"season": 1, "episode": 1}]
    listed = authed_client.get("/api/series").json()["series"][0]
    assert listed["missing_count"] == 1
    assert listed["listings_complete"] is True


def test_list_missing_count_zero_when_complete(authed_client, tmp_path) -> None:
    _configured_shows(tmp_path, ["Clip"])
    _cache_view(authed_client, tmp_path, "clip", on_disk=[(1, 1), (1, 2)])
    listed = authed_client.get("/api/series").json()["series"][0]
    assert listed["missing_count"] == 0
    assert listed["listings_complete"] is True


def test_get_episodes_does_not_extract_or_write_cache(authed_client, tmp_path, monkeypatch) -> None:
    _configured_shows(tmp_path, ["Clip"])

    def forbidden(*args, **kwargs):
        raise AssertionError("GET must never fetch provider listings")

    monkeypatch.setattr("yt_dlp_emby.server.services.extract_dropout_season", forbidden)
    response = authed_client.get("/api/series/dropout/clip/sources/0/seasons/0/episodes")
    assert response.status_code == 200
    assert response.json()["episodes"] == []
    assert response.json()["refresh_required"] is True
    assert not (tmp_path / "dropout-cache.json").exists()
    assert authed_client.get("/api/series").json()["series"][0]["missing_count"] is None


def test_uncached_missing_endpoint_reports_unknown_without_provider_io(
    authed_client, tmp_path, monkeypatch
) -> None:
    _configured_shows(tmp_path, ["Clip"])

    def forbidden(*args, **kwargs):
        raise AssertionError("GET must never fetch provider listings")

    monkeypatch.setattr("yt_dlp_emby.server.services.extract_dropout_season", forbidden)
    body = authed_client.get("/api/series/dropout/clip/missing").json()
    assert body["missing_count"] is None
    assert body["complete"] is False
    assert body["stale"] is True
    assert body["error"]


def test_job_target_uses_file_stem_when_name_has_apostrophe(authed_client, tmp_path) -> None:
    shows = tmp_path / "shows"
    shows.mkdir()
    (shows / "dimension-20-adventuring-party.yaml").write_text(
        "series:\n  - name: Dimension 20's Adventuring Party\n    path: AP\n    tvdb_id: 391568\n    seasons: []\n"
    )
    (tmp_path / "dropout.yaml").write_text(
        "imports: [shows/dimension-20-adventuring-party.yaml]\nseries: []\n"
    )
    listed = authed_client.get("/api/series").json()["series"]
    assert listed[0]["slug"] == "dimension-20-adventuring-party"
    response = authed_client.post(
        "/api/jobs",
        json={"kind": "check", "items": [{"platform": "dropout", "slug": listed[0]["slug"]}]},
    )
    assert response.status_code == 202, response.text


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
            "/api/jobs",
            json={"kind": "refresh", "items": [{"platform": "dropout", "slug": "solo"}]},
        ).status_code
        == 401
    )


def test_refresh_empty_items_400(authed_client, tmp_path) -> None:
    assert authed_client.post("/api/jobs", json={"kind": "refresh", "items": []}).status_code == 400


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


def test_explicit_refresh_fetches_provider_despite_legacy_cache(
    authed_client, tmp_path, monkeypatch
) -> None:
    from yt_dlp_emby.cache import dropout_cache_path, save_dropout_season_cache
    from yt_dlp_emby.extract import DropoutListing
    from yt_dlp_emby.server.services import refresh_target

    _configured_shows(tmp_path, ["Clip"])
    page = "https://watch.dropout.tv/clip/season:1"
    save_dropout_season_cache(
        dropout_cache_path(tmp_path / "dropout.yaml"),
        {
            page: [
                {"url": "https://watch.dropout.tv/videos/old", "title": "Old", "dropout_episode": 1}
            ]
        },
    )
    fetched = []
    monkeypatch.setattr(
        "yt_dlp_emby.server.services.discover_dropout_source",
        lambda *args, **kwargs: [{"dropout": 1, "url": page, "to_season": 1, "enabled": True}],
    )

    def extract(url, **kwargs):
        fetched.append(url)
        return [
            DropoutListing(
                url="https://watch.dropout.tv/videos/new", title="New", dropout_episode=1
            )
        ]

    monkeypatch.setattr("yt_dlp_emby.server.services.extract_dropout_season", extract)
    result = refresh_target(tmp_path, {}, {"platform": "dropout", "slug": "clip"})
    assert result["ok"] is True
    assert fetched == [page]
    assert result["view"]["provider_listings"][0]["title"] == "New"
    assert not (tmp_path / "library" / "Clip").exists()


def _configured_shows(data: Path, names: list[str]) -> None:
    library = data / "library"
    library.mkdir(exist_ok=True)
    entries = [
        {
            "name": name,
            "path": name,
            "url": f"https://watch.dropout.tv/{name.lower()}",
            "seasons": [{"dropout": 1, "url": f"https://watch.dropout.tv/{name.lower()}/season:1"}],
        }
        for name in names
    ]
    (data / "dropout.yaml").write_text(
        yaml.safe_dump({"library": str(library), "old_dir": str(data / "old"), "series": entries})
    )


def _cache_view(
    client: TestClient, data: Path, slug: str, *, on_disk: list[tuple[int, int]] | None = None
) -> dict:
    from dataclasses import asdict
    from datetime import datetime, timezone

    from yt_dlp_emby.server.series import locate_series
    from yt_dlp_emby.server.services import (
        ProviderListing,
        current_configuration_revision,
        plan_variant,
    )
    from yt_dlp_emby.server.views import configuration_context_signature, source_signature

    rows = [
        ProviderListing(
            platform="dropout",
            source_index=0,
            season_index=0,
            source_season=1,
            destination_season=1,
            episode=number,
            identity=f"{slug}:episode:{number}",
            title=title,
            url=f"https://watch.dropout.tv/videos/{slug}-{number}",
            mapped_episode=number,
        )
        for number, title in ((1, "Pilot"), (2, "Two"))
    ]
    view = {
        "target": {"platform": "dropout", "slug": slug},
        "config_revision": current_configuration_revision(data, {}, "dropout", slug),
        "provider_listings": [asdict(row) for row in rows],
        "disk": {
            "status": "ready",
            "series_exists": True,
            "episodes": [list(pair) for pair in on_disk or []],
            "episode_fingerprints": [],
            "revision": f"disk-{slug}",
            "scanned_at": "2026-01-01T00:00:00Z",
            "mount_identity": "test-mount",
        },
        "stale": False,
    }
    _, series = locate_series(data, "dropout", slug)
    view["source_signature"] = source_signature(series)
    view["context_signature"] = configuration_context_signature(data, {}, "dropout")
    plan = plan_variant(view)
    cached_at = datetime.now(timezone.utc).isoformat()
    client.app.state.job_store.put_view(
        "dropout",
        slug,
        {"view": view},
        plan,
        plan["revision"],
        "ready",
        cached_at,
        cached_at,
    )
    return view


def test_cached_plan_preserves_both_shows_on_same_platform(authed_client, tmp_path) -> None:
    _configured_shows(tmp_path, ["Show", "Other"])
    _cache_view(authed_client, tmp_path, "show")
    _cache_view(authed_client, tmp_path, "other")
    plan = authed_client.get("/api/queue").json()
    assert {row["slug"] for row in plan["sources"]["dropout"]["items"]} == {"show", "other"}
    assert len(plan["sources"]["dropout"]["items"]) == 4


def test_failed_refresh_preserves_last_good_view_as_stale(authed_client, tmp_path) -> None:
    _configured_shows(tmp_path, ["Show", "Other"])
    _cache_view(authed_client, tmp_path, "show")
    _cache_view(authed_client, tmp_path, "other")
    authed_client.app.state.job_store.record_view_attempt("dropout", "show", "NAS unavailable")
    plan = authed_client.get("/api/queue").json()
    rows = plan["sources"]["dropout"]["items"]
    assert all(row["action"] == "download" for row in rows if row["slug"] == "show")
    assert all(row["action"] == "download" for row in rows if row["slug"] == "other")
    assert plan["stale"] is True
    assert plan["cache_errors"][0]["error"] == "NAS unavailable"
    detail = authed_client.get("/api/series/dropout/show").json()
    assert detail["stale"] is True
    assert detail["missing_count"] == 2
    assert (
        detail["last_success_at"]
        == authed_client.app.state.job_store.get_view("dropout", "show")["last_success_at"]
    )
    assert detail["error"] == "NAS unavailable"


def test_external_config_change_blocks_cached_execution(authed_client, tmp_path) -> None:
    _configured_shows(tmp_path, ["Show"])
    _cache_view(authed_client, tmp_path, "show")
    before = authed_client.get("/api/queue").json()
    path = tmp_path / "dropout.yaml"
    raw = yaml.safe_load(path.read_text())
    raw["series"][0]["seasons"][0]["to_season"] = 27
    path.write_text(yaml.safe_dump(raw))
    after = authed_client.get("/api/queue").json()
    assert before["plan_id"] != after["plan_id"]
    assert after["readiness"] == "stale"
    assert all(row["action"] == "blocked" for row in after["sources"]["dropout"]["items"])
    started = authed_client.post(
        "/api/jobs",
        json={
            "kind": "download",
            "ids": [before["sources"]["dropout"]["items"][0]["id"]],
        },
    )
    assert started.status_code == 409
    assert started.json()["code"] == "PLAN_STALE"
    active = authed_client.get("/api/jobs").json()["active"]
    assert active is None or active["kind"] == "refresh"


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


def test_plans_latest_uses_cached_disk_snapshot(authed_client, tmp_path, monkeypatch) -> None:
    _configured_shows(tmp_path, ["Clip"])
    _cache_view(authed_client, tmp_path, "clip", on_disk=[(1, 1)])

    def forbidden(*args, **kwargs):
        raise AssertionError("cached plan GET must never scan media")

    monkeypatch.setattr("yt_dlp_emby.server.services.library_snapshot", forbidden)
    plan = authed_client.get("/api/queue").json()
    rows = plan["sources"]["dropout"]["items"]
    assert [row["code"] for row in rows if row["action"] == "download"] == ["S01E02"]
    assert authed_client.get("/api/series").json()["series"][0]["missing_count"] == 1


def test_mapping_save_replans_only_target_without_provider_or_disk_io(
    authed_client, tmp_path, monkeypatch
) -> None:
    _configured_shows(tmp_path, ["Show", "Other"])
    _cache_view(authed_client, tmp_path, "show")
    _cache_view(authed_client, tmp_path, "other")
    calls = []

    def forbidden(*args, **kwargs):
        calls.append(args)
        raise AssertionError("mapping save must use cached inputs")

    monkeypatch.setattr("yt_dlp_emby.server.services.extract_dropout_season", forbidden)
    monkeypatch.setattr("yt_dlp_emby.server.services.library_snapshot", forbidden)
    monkeypatch.setattr("yt_dlp_emby.dropout.run_dropout", forbidden)
    detail = authed_client.get("/api/series/dropout/show").json()
    detail["sources"][0]["seasons"][0]["remaps"] = [{"dropout_episode": 1, "skip": True}]
    saved = authed_client.put("/api/series/dropout/show", json=detail)
    assert saved.status_code == 200, saved.text
    assert not calls
    plan = authed_client.get("/api/queue").json()
    rows = plan["sources"]["dropout"]["items"]
    assert not any(
        row["slug"] == "show" and row["provider_identity"] == "show:episode:1" for row in rows
    )
    assert all(row["action"] == "download" for row in rows if row["slug"] == "other")


def test_source_url_save_requires_refresh_instead_of_trusting_old_listings(
    authed_client, tmp_path
) -> None:
    _configured_shows(tmp_path, ["Show"])
    _cache_view(authed_client, tmp_path, "show")
    detail = authed_client.get("/api/series/dropout/show").json()
    detail["sources"][0]["url"] = "https://watch.dropout.tv/different"
    saved = authed_client.put("/api/series/dropout/show", json=detail)
    assert saved.status_code == 200, saved.text
    plan = authed_client.get("/api/queue").json()
    assert plan["readiness"] == "stale"
    assert all(row["action"] == "blocked" for row in plan["sources"]["dropout"]["items"])
    assert authed_client.get("/api/series/dropout/show/missing").json()["missing_count"] is None


def test_external_library_setting_edit_cannot_be_blessed_by_mapping_save(
    authed_client, tmp_path
) -> None:
    _configured_shows(tmp_path, ["Show"])
    _cache_view(authed_client, tmp_path, "show")
    (tmp_path / "config.toml").write_text('[fallback]\nlibrary="/different-library"\n')
    detail = authed_client.get("/api/series/dropout/show").json()
    detail["sources"][0]["seasons"][0]["to_season"] = 27
    saved = authed_client.put("/api/series/dropout/show", json=detail)
    assert saved.status_code == 200, saved.text
    assert authed_client.get("/api/queue").json()["readiness"] == "stale"
