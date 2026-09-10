"""Load and validate a nested Dropout YAML manifest."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import yaml

from yt_emby.config import ConfigError
from yt_emby.cookies import cookies_file_usable

__all__ = [
    "DropoutManifest",
    "DropoutRemap",
    "DropoutSeason",
    "DropoutSeries",
    "load_dropout_manifest",
    "filter_dropout_manifest",
    "season_page_url",
]


@dataclass(frozen=True)
class DropoutRemap:
    dropout_episode: int
    to_season: int
    to_episode: int
    title: str | None = None


@dataclass(frozen=True)
class DropoutSeason:
    dropout: int | None = None
    url: str | None = None
    to_season: int | None = None
    remap: tuple[DropoutRemap, ...] = ()
    only_episodes: tuple[int, ...] | None = None


@dataclass(frozen=True)
class DropoutSeries:
    name: str
    path: str
    url: str | None = None
    seasons: tuple[DropoutSeason, ...] = ()


@dataclass(frozen=True)
class DropoutManifest:
    library: Path
    old_dir: Path
    series: tuple[DropoutSeries, ...]
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


def _int_field(value: Any, key: str, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigError(f"{key} must be an integer in {context}")
    return value


def _parse_only_episodes(raw: Any, context: str) -> tuple[int, ...] | None:
    if raw is None:
        return None
    if not isinstance(raw, list) or not raw:
        raise ConfigError(f"only_episodes must be a non-empty list in {context}")
    seen: set[int] = set()
    numbers: list[int] = []
    for item in raw:
        number = _int_field(item, "only_episodes", context)
        if number < 1:
            raise ConfigError(f"only_episodes values must be >= 1 in {context}")
        if number in seen:
            continue
        seen.add(number)
        numbers.append(number)
    return tuple(numbers)


def _parse_remap(raw: Any, context: str) -> DropoutRemap:
    if not isinstance(raw, dict):
        raise ConfigError(f"remap entry must be a mapping in {context}")
    title_raw = raw.get("title")
    title = None
    if title_raw is not None:
        if not isinstance(title_raw, str) or not title_raw.strip():
            raise ConfigError(f"title must be a non-empty string in {context}")
        title = title_raw.strip()
    return DropoutRemap(
        dropout_episode=_int_field(raw.get("dropout_episode"), "dropout_episode", context),
        to_season=_int_field(raw.get("to_season"), "to_season", context),
        to_episode=_int_field(raw.get("to_episode"), "to_episode", context),
        title=title,
    )


def _parse_season(raw: Any, series_name: str, index: int) -> DropoutSeason:
    context = f"series {series_name!r} season {index}"
    if not isinstance(raw, dict):
        raise ConfigError(f"Season entry must be a mapping in {context}")
    dropout = raw.get("dropout")
    url = raw.get("url")
    if dropout is not None:
        dropout = _int_field(dropout, "dropout", context)
    if url is not None:
        url = str(url).strip() or None
    if dropout is None and not url:
        raise ConfigError(f"Season needs dropout or url in {context}")
    to_season = raw.get("to_season")
    if to_season is not None:
        to_season = _int_field(to_season, "to_season", context)
    remaps = raw.get("remap") or []
    if not isinstance(remaps, list):
        raise ConfigError(f"remap must be a list in {context}")
    parsed = tuple(_parse_remap(item, context) for item in remaps)
    only_episodes = _parse_only_episodes(raw.get("only_episodes"), context)
    if to_season is None and not parsed and dropout is None:
        raise ConfigError(f"Season needs to_season, remap, or dropout in {context}")
    return DropoutSeason(
        dropout=dropout,
        url=url,
        to_season=to_season,
        remap=parsed,
        only_episodes=only_episodes,
    )


def _parse_series(raw: Any, index: int) -> DropoutSeries:
    context = f"series[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"Series entry must be a mapping in {context}")
    name = _require_str(raw, "name", context)
    path = _require_str(raw, "path", context)
    url = raw.get("url")
    if url is not None:
        url = str(url).strip() or None
    seasons_raw = raw.get("seasons") or []
    if not isinstance(seasons_raw, list) or not seasons_raw:
        raise ConfigError(f"Series {name!r} needs a non-empty seasons list")
    seasons = tuple(_parse_season(item, name, i) for i, item in enumerate(seasons_raw, start=1))
    for season in seasons:
        if season.dropout is not None and not season.url and not url:
            raise ConfigError(
                f"Series {name!r} needs url when a season uses dropout: {season.dropout}"
            )
    return DropoutSeries(name=name, path=path, url=url, seasons=seasons)


def season_page_url(series: DropoutSeries, season: DropoutSeason) -> str:
    if season.url:
        return season.url.rstrip("/")
    assert series.url is not None and season.dropout is not None
    return f"{series.url.rstrip('/')}/season:{season.dropout}"


def load_dropout_manifest(path: Path) -> DropoutManifest:
    if not path.is_file():
        raise ConfigError(f"Dropout manifest not found: {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ConfigError(f"Dropout manifest must be a mapping: {path}")
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
    return DropoutManifest(
        library=Path(library),
        old_dir=Path(old_dir),
        series=series,
        staging=_optional_path(data.get("staging")),
        cookies=cookies,
        path=path,
    )


def _series_matches(series: DropoutSeries, needles: Sequence[str]) -> bool:
    name = series.name.lower()
    path = series.path.lower()
    for raw in needles:
        needle = raw.lower().strip()
        if not needle:
            continue
        if needle == name or needle == path or needle in name or needle in path:
            return True
    return False


def filter_dropout_manifest(
    manifest: DropoutManifest,
    *,
    series_names: Sequence[str] | None = None,
    dropout_seasons: Sequence[int] | None = None,
) -> DropoutManifest:
    names = [item for item in (series_names or []) if item and str(item).strip()]
    seasons = list(dropout_seasons or [])
    if not names and not seasons:
        return manifest
    kept: list[DropoutSeries] = []
    for series in manifest.series:
        if names and not _series_matches(series, names):
            continue
        selected = series.seasons
        if seasons:
            selected = tuple(
                season
                for season in series.seasons
                if season.dropout is not None and season.dropout in seasons
            )
        if not selected:
            continue
        kept.append(replace(series, seasons=selected))
    if not kept:
        raise ConfigError("No series/seasons matched --series/--season")
    return replace(manifest, series=tuple(kept))
