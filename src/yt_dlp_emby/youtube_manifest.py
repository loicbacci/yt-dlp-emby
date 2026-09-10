"""Load and validate a YouTube YAML manifest."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import yaml

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.cookies import cookies_file_usable

__all__ = [
    "YoutubeManifest",
    "YoutubePlaylist",
    "YoutubeSeries",
    "load_youtube_manifest",
    "filter_youtube_manifest",
]


@dataclass(frozen=True)
class YoutubePlaylist:
    url: str
    season: int | None = None


@dataclass(frozen=True)
class YoutubeSeries:
    name: str
    playlists: tuple[YoutubePlaylist, ...]


@dataclass(frozen=True)
class YoutubeManifest:
    library: Path
    old_dir: Path
    series: tuple[YoutubeSeries, ...]
    staging: Path | None = None
    cookies: Path | None = None
    path: Path | None = None


def _require_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing {key} in {context}")
    return value.strip()


def _optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))


def _parse_playlist(raw: Any, context: str) -> YoutubePlaylist:
    if not isinstance(raw, dict):
        raise ConfigError(f"Playlist entry must be a mapping in {context}")
    url = _require_str(raw, "url", context)
    season = raw.get("season")
    if season is not None:
        if isinstance(season, bool) or not isinstance(season, int) or season < 1:
            raise ConfigError(f"season must be an integer >= 1 in {context}")
    return YoutubePlaylist(url=url, season=season)


def _parse_series(raw: Any, index: int) -> YoutubeSeries:
    context = f"series[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"Series entry must be a mapping in {context}")
    name = _require_str(raw, "name", context)
    playlists_raw = raw.get("playlists") or []
    if not isinstance(playlists_raw, list) or not playlists_raw:
        raise ConfigError(f"Series {name!r} needs a non-empty playlists list")
    playlists = tuple(
        _parse_playlist(item, f"{context} playlist {i}")
        for i, item in enumerate(playlists_raw, start=1)
    )
    seen: set[str] = set()
    for item in playlists:
        if item.url in seen:
            raise ConfigError(f"Duplicate playlist URL in series {name!r}: {item.url}")
        seen.add(item.url)
    return YoutubeSeries(name=name, playlists=playlists)


def load_youtube_manifest(path: Path) -> YoutubeManifest:
    if not path.is_file():
        raise ConfigError(f"YouTube manifest not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"YouTube manifest must be a mapping: {path}")
    library = _require_str(data, "library", str(path))
    old_dir = _require_str(data, "old_dir", str(path))
    series_raw = data.get("series") or []
    if not isinstance(series_raw, list) or not series_raw:
        raise ConfigError("Manifest needs a non-empty series list")
    series = tuple(_parse_series(item, i) for i, item in enumerate(series_raw, start=1))
    cookies = _optional_path(data.get("cookies"))
    if cookies is not None and not cookies.is_absolute():
        cookies = path.parent / cookies
    if cookies is not None and not cookies.is_file():
        raise ConfigError(f"Cookies file not found: {cookies}")
    if cookies is not None and not cookies_file_usable(cookies):
        raise ConfigError(f"Cookies file is empty: {cookies}")
    return YoutubeManifest(
        library=Path(library),
        old_dir=Path(old_dir),
        series=series,
        staging=_optional_path(data.get("staging")),
        cookies=cookies,
        path=path,
    )


def _name_matches(series: YoutubeSeries, needles: Sequence[str]) -> bool:
    name = series.name.lower()
    for raw in needles:
        needle = raw.lower().strip()
        if needle and (needle == name or needle in name):
            return True
    return False


def filter_youtube_manifest(
    manifest: YoutubeManifest,
    *,
    series_names: Sequence[str] | None = None,
) -> YoutubeManifest:
    names = [item for item in (series_names or []) if item and str(item).strip()]
    if not names:
        return manifest
    needles = [item.lower().strip() for item in names]
    kept: list[YoutubeSeries] = []
    for series in manifest.series:
        if _name_matches(series, names):
            kept.append(series)
            continue
        selected = tuple(
            item
            for item in series.playlists
            if any(needle in item.url.lower() for needle in needles)
        )
        if selected:
            kept.append(replace(series, playlists=selected))
    if not kept:
        raise ConfigError("No series matched --series")
    return replace(manifest, series=tuple(kept))
