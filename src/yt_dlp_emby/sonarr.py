"""Fetch Sonarr series/episode lists by TVDB id."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from yt_dlp_emby.cache import DROPOUT_CACHE_DIRNAME
from yt_dlp_emby.config import ConfigError

SONARR_CACHE_FILENAME = "sonarr.json"
TIMEOUT_SECONDS = 30

GetJson = Callable[[str, dict[str, str]], Any]


@dataclass(frozen=True)
class SonarrEpisode:
    season: int
    episode: int
    title: str
    air_date: str | None = None


def sonarr_cache_path(manifest_path: Path | None = None, *, cwd: Path | None = None) -> Path:
    root = manifest_path.parent if manifest_path is not None else (cwd or Path.cwd())
    return root / DROPOUT_CACHE_DIRNAME / SONARR_CACHE_FILENAME


def load_sonarr_cache(path: Path) -> dict[str, dict]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict] = {}
    for key, value in data.items():
        if isinstance(value, dict):
            result[str(key)] = value
    return result


def save_sonarr_cache(path: Path, payload: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _default_get_json(url: str, headers: dict[str, str]) -> Any:
    request = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raise exc
    except OSError as exc:
        raise ConfigError(f"Sonarr request failed: {exc}") from exc
    try:
        return json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError("Sonarr returned invalid JSON") from exc


def _parse_air_date(raw: Any) -> str | None:
    if not isinstance(raw, str):
        return None
    text = raw.strip()
    if len(text) >= 10 and text[4] == "-" and text[7] == "-":
        return text[:10]
    return None


def _raise_http(exc: urllib.error.HTTPError) -> None:
    if exc.code in (401, 403):
        raise ConfigError("Sonarr API key rejected") from exc
    raise ConfigError(f"Sonarr request failed: HTTP {exc.code}") from exc


def fetch_episodes(
    tvdb_id: int,
    *,
    base_url: str,
    api_key: str,
    get_json: GetJson | None = None,
) -> tuple[str, list[SonarrEpisode]]:
    get = get_json or _default_get_json
    base = base_url.rstrip("/")
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    try:
        series_list = get(f"{base}/api/v3/series?tvdbId={tvdb_id}", headers)
    except urllib.error.HTTPError as exc:
        _raise_http(exc)
    if not isinstance(series_list, list) or not series_list:
        raise ConfigError(f"Sonarr has no series with tvdb_id={tvdb_id}")
    first = series_list[0]
    if not isinstance(first, dict) or first.get("id") is None:
        raise ConfigError(f"Sonarr has no series with tvdb_id={tvdb_id}")
    series_id = first["id"]
    title = str(first.get("title") or "").strip() or f"tvdb_id={tvdb_id}"
    try:
        raw_episodes = get(f"{base}/api/v3/episode?seriesId={series_id}", headers)
    except urllib.error.HTTPError as exc:
        _raise_http(exc)
    if not isinstance(raw_episodes, list):
        raise ConfigError("Sonarr episode list was not an array")
    episodes: list[SonarrEpisode] = []
    for item in raw_episodes:
        if not isinstance(item, dict):
            continue
        number = item.get("episodeNumber")
        season = item.get("seasonNumber")
        if number is None or season is None:
            continue
        if isinstance(number, bool) or isinstance(season, bool):
            continue
        if not isinstance(number, int) or not isinstance(season, int):
            continue
        episodes.append(
            SonarrEpisode(
                season=season,
                episode=number,
                title=str(item.get("title") or "").strip(),
                air_date=_parse_air_date(item.get("airDate") or item.get("airDateUtc")),
            )
        )
    return title, episodes


def _episodes_from_cache(raw: dict) -> tuple[str, list[SonarrEpisode]]:
    title = str(raw.get("title") or "")
    items = raw.get("episodes") or []
    episodes: list[SonarrEpisode] = []
    if isinstance(items, list):
        for item in items:
            if not isinstance(item, dict):
                continue
            season = item.get("season")
            episode = item.get("episode")
            if not isinstance(season, int) or not isinstance(episode, int):
                continue
            episodes.append(
                SonarrEpisode(
                    season=season,
                    episode=episode,
                    title=str(item.get("title") or ""),
                    air_date=_parse_air_date(item.get("air_date")),
                )
            )
    return title, episodes


def fetch_episodes_cached(
    tvdb_id: int,
    *,
    base_url: str,
    api_key: str,
    cache_path: Path,
    force_refetch: bool = False,
    get_json: GetJson | None = None,
) -> tuple[str, list[SonarrEpisode]]:
    key = str(tvdb_id)
    if not force_refetch:
        cached = load_sonarr_cache(cache_path).get(key)
        if cached is not None:
            return _episodes_from_cache(cached)
    title, episodes = fetch_episodes(
        tvdb_id,
        base_url=base_url,
        api_key=api_key,
        get_json=get_json,
    )
    cache = load_sonarr_cache(cache_path)
    cache[key] = {
        "title": title,
        "episodes": [
            {
                "season": item.season,
                "episode": item.episode,
                "title": item.title,
                "air_date": item.air_date,
            }
            for item in episodes
        ],
    }
    save_sonarr_cache(cache_path, cache)
    return title, episodes
