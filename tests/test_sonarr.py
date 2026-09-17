from io import BytesIO
from pathlib import Path
from urllib.error import HTTPError

import pytest

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.sonarr import (
    fetch_episodes,
    load_sonarr_cache,
    ping_sonarr,
    save_sonarr_cache,
    sonarr_cache_path,
)


def test_fetch_episodes_uses_tvdb_then_series_id() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def get_json(url: str, headers: dict[str, str]) -> list | dict:
        calls.append((url, headers))
        if "series?" in url:
            return [{"id": 42, "title": "Game Changer", "titleSlug": "game-changer"}]
        return [
            {"seasonNumber": 1, "episodeNumber": 4, "title": "Slug Eater", "airDate": "2020-03-26"},
            {"seasonNumber": 0, "episodeNumber": 12, "title": "Cut for Time"},
        ]

    extra: dict = {}
    title, episodes = fetch_episodes(
        361151,
        base_url="http://localhost:8989/",
        api_key="secret-key",
        get_json=get_json,
        extra=extra,
    )
    assert title == "Game Changer"
    assert extra["title_slug"] == "game-changer"
    assert [(ep.season, ep.episode, ep.title, ep.air_date) for ep in episodes] == [
        (1, 4, "Slug Eater", "2020-03-26"),
        (0, 12, "Cut for Time", None),
    ]
    assert calls[0][0] == "http://localhost:8989/api/v3/series?tvdbId=361151"
    assert calls[1][0] == "http://localhost:8989/api/v3/episode?seriesId=42"
    assert calls[0][1]["X-Api-Key"] == "secret-key"
    assert "secret-key" not in calls[0][0]


def test_skips_null_episode_number() -> None:
    def get_json(url: str, headers: dict[str, str]) -> list | dict:
        if "series?" in url:
            return [{"id": 1, "title": "Show"}]
        return [
            {"seasonNumber": 1, "episodeNumber": None, "title": "TBA"},
            {"seasonNumber": 1, "episodeNumber": 2, "title": "Named"},
        ]

    _title, episodes = fetch_episodes(1, base_url="http://sonarr", api_key="k", get_json=get_json)
    assert [(ep.season, ep.episode, ep.title) for ep in episodes] == [(1, 2, "Named")]


def test_empty_series_list_errors() -> None:
    def get_json(url: str, headers: dict[str, str]) -> list | dict:
        return []

    with pytest.raises(ConfigError, match="tvdb_id=361151"):
        fetch_episodes(361151, base_url="http://sonarr", api_key="k", get_json=get_json)


def test_401_errors() -> None:
    def get_json(url: str, headers: dict[str, str]) -> list | dict:
        raise HTTPError(url, 401, "Unauthorized", hdrs=None, fp=BytesIO())

    with pytest.raises(ConfigError, match="API key rejected"):
        fetch_episodes(1, base_url="http://sonarr", api_key="bad", get_json=get_json)


def test_ping_sonarr_reads_status() -> None:
    calls: list[tuple[str, dict[str, str]]] = []

    def get_json(url: str, headers: dict[str, str]) -> dict:
        calls.append((url, headers))
        return {"appName": "Sonarr", "instanceName": "Home", "version": "4.0.1.9290"}

    result = ping_sonarr(base_url="http://localhost:8989/", api_key="secret-key", get_json=get_json)
    assert result == {
        "ok": True,
        "version": "4.0.1.9290",
        "instance": "Home",
    }
    assert calls[0][0] == "http://localhost:8989/api/v3/system/status"
    assert calls[0][1]["X-Api-Key"] == "secret-key"


def test_ping_sonarr_401() -> None:
    def get_json(url: str, headers: dict[str, str]) -> dict:
        raise HTTPError(url, 401, "Unauthorized", hdrs=None, fp=BytesIO())

    with pytest.raises(ConfigError, match="API key rejected"):
        ping_sonarr(base_url="http://sonarr", api_key="bad", get_json=get_json)


def test_ping_sonarr_rejects_non_object() -> None:
    def get_json(url: str, headers: dict[str, str]) -> list:
        return []

    with pytest.raises(ConfigError, match="not an object"):
        ping_sonarr(base_url="http://sonarr", api_key="k", get_json=get_json)


def test_sonarr_cache_roundtrip(tmp_path: Path) -> None:
    path = sonarr_cache_path(tmp_path / "dropout.yaml")
    assert path == tmp_path / "cache" / "sonarr.json"
    payload = {
        "361151": {
            "title": "Game Changer",
            "episodes": [{"season": 1, "episode": 4, "title": "Slug Eater"}],
        }
    }
    save_sonarr_cache(path, payload)
    loaded = load_sonarr_cache(path)
    assert loaded["361151"]["title"] == "Game Changer"
    assert loaded["361151"]["episodes"][0]["episode"] == 4


def test_force_refetch_skips_cache(tmp_path: Path) -> None:
    from yt_dlp_emby.sonarr import fetch_episodes_cached

    path = sonarr_cache_path(tmp_path / "dropout.yaml")
    save_sonarr_cache(
        path,
        {
            "1": {
                "title": "Cached",
                "episodes": [{"season": 1, "episode": 1, "title": "Old"}],
            }
        },
    )
    calls: list[int] = []

    def get_json(url: str, headers: dict[str, str]) -> list | dict:
        calls.append(1)
        if "series?" in url:
            return [{"id": 9, "title": "Fresh"}]
        return [{"seasonNumber": 1, "episodeNumber": 1, "title": "New"}]

    cached_title, cached_eps = fetch_episodes_cached(
        1,
        base_url="http://sonarr",
        api_key="k",
        cache_path=path,
        force_refetch=False,
        get_json=get_json,
    )
    assert cached_title == "Cached"
    assert cached_eps[0].title == "Old"
    assert calls == []

    fresh_title, fresh_eps = fetch_episodes_cached(
        1,
        base_url="http://sonarr",
        api_key="k",
        cache_path=path,
        force_refetch=True,
        get_json=get_json,
    )
    assert fresh_title == "Fresh"
    assert fresh_eps[0].title == "New"
    assert calls
    reread = load_sonarr_cache(path)
    assert reread["1"]["title"] == "Fresh"
