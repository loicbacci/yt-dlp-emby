"""Load and validate a nested Dropout YAML manifest."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import yaml

from yt_dlp_emby.config import ConfigError, format_yaml_error
from yt_dlp_emby.cookies import cookies_file_usable

__all__ = [
    "CHILD_FORBIDDEN_KEYS",
    "DropoutManifest",
    "DropoutRemap",
    "DropoutSeason",
    "DropoutSeries",
    "DropoutSource",
    "filter_dropout_manifest",
    "load_dropout_manifest",
    "merge_series_by_path",
    "parse_dropout_manifest",
    "parse_dropout_series_file",
    "season_page_url",
]

CHILD_FORBIDDEN_KEYS = frozenset({"library", "old_dir", "cookies", "staging", "imports"})


@dataclass(frozen=True)
class DropoutRemap:
    dropout_episode: int
    to_season: int | None = None
    to_episode: int | None = None
    title: str | None = None
    skip: bool = False


@dataclass(frozen=True)
class DropoutSeason:
    dropout: int | None = None
    url: str | None = None
    to_season: int | None = None
    remap: tuple[DropoutRemap, ...] = ()
    only_episodes: tuple[int, ...] | None = None
    enabled: bool = True
    title: str | None = None


@dataclass(frozen=True)
class DropoutSource:
    url: str | None
    seasons: tuple[DropoutSeason, ...]


@dataclass(frozen=True)
class DropoutSeries:
    name: str
    path: str
    sources: tuple[DropoutSource, ...]
    tvdb_id: int | None = None
    tvdb_skip: frozenset[tuple[int, int]] = frozenset()


@dataclass(frozen=True)
class DropoutManifest:
    library: Path | None = None
    old_dir: Path | None = None
    series: tuple[DropoutSeries, ...] = ()
    staging: Path | None = None
    cookies: Path | None = None
    path: Path | None = None
    imports: tuple[str, ...] = ()


def _require_str(data: dict[str, Any], key: str, context: str) -> str:
    value = data.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Missing {key} in {context}")
    return value.strip()


def _optional_path(value: Any) -> Path | None:
    if value is None or value == "":
        return None
    return Path(str(value))


def _optional_str_path(value: Any, key: str, context: str) -> Path | None:
    if value is None or value == "":
        return None
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"{key} must be a string in {context}")
    return Path(value.strip())


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
    skip_raw = raw.get("skip")
    if skip_raw is not None and not isinstance(skip_raw, bool):
        raise ConfigError(f"skip must be a boolean in {context}")
    skip = bool(skip_raw)
    title_raw = raw.get("title")
    title = None
    if title_raw is not None:
        if not isinstance(title_raw, str) or not title_raw.strip():
            raise ConfigError(f"title must be a non-empty string in {context}")
        title = title_raw.strip()
    dropout_episode = _int_field(raw.get("dropout_episode"), "dropout_episode", context)
    if skip:
        return DropoutRemap(dropout_episode=dropout_episode, skip=True)
    to_season = raw.get("to_season")
    to_episode = raw.get("to_episode")
    if to_season is None:
        raise ConfigError(f"to_season is required in {context}")
    if to_episode is None:
        raise ConfigError(f"to_episode is required in {context}")
    return DropoutRemap(
        dropout_episode=dropout_episode,
        to_season=_int_field(to_season, "to_season", context),
        to_episode=_int_field(to_episode, "to_episode", context),
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
    enabled_raw = raw.get("enabled")
    if enabled_raw is not None and not isinstance(enabled_raw, bool):
        raise ConfigError(f"enabled must be a boolean in {context}")
    enabled = True if enabled_raw is None else bool(enabled_raw)
    title_raw = raw.get("title")
    title = None
    if title_raw is not None:
        if not isinstance(title_raw, str) or not title_raw.strip():
            raise ConfigError(f"title must be a non-empty string in {context}")
        title = title_raw.strip()
    return DropoutSeason(
        dropout=dropout,
        url=url,
        to_season=to_season,
        remap=parsed,
        only_episodes=only_episodes,
        enabled=enabled,
        title=title,
    )


def _optional_url(raw: Any) -> str | None:
    if raw is None:
        return None
    return str(raw).strip() or None


def _validate_source_urls(source: DropoutSource, name: str) -> None:
    for season in source.seasons:
        if season.dropout is not None and not season.url and not source.url:
            raise ConfigError(
                f"Series {name!r} needs url when a season uses dropout: {season.dropout}"
            )


def _parse_source_item(raw: Any, name: str, index: int) -> DropoutSource:
    context = f"series {name!r} urls[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"urls item must be a mapping in {context}")
    seasons_raw = raw.get("seasons")
    if not isinstance(seasons_raw, list) or not seasons_raw:
        raise ConfigError(f"urls item needs a non-empty seasons list in {context}")
    seasons = tuple(_parse_season(item, name, i) for i, item in enumerate(seasons_raw, start=1))
    source = DropoutSource(url=_optional_url(raw.get("url")), seasons=seasons)
    _validate_source_urls(source, name)
    return source


def _parse_tvdb_skip(raw: Any, context: str) -> frozenset[tuple[int, int]]:
    if raw is None:
        return frozenset()
    if not isinstance(raw, list):
        raise ConfigError(f"tvdb_skip must be a list in {context}")
    pairs: set[tuple[int, int]] = set()
    for i, block in enumerate(raw, start=1):
        block_ctx = f"{context} tvdb_skip[{i}]"
        if not isinstance(block, dict):
            raise ConfigError(f"tvdb_skip entry must be a mapping in {block_ctx}")
        season = _int_field(block.get("season"), "season", block_ctx)
        if season < 0:
            raise ConfigError(f"season must be >= 0 in {block_ctx}")
        episodes = block.get("episodes")
        if not isinstance(episodes, list) or not episodes:
            raise ConfigError(f"episodes must be a non-empty list in {block_ctx}")
        for item in episodes:
            number = _int_field(item, "episodes", block_ctx)
            if number < 1:
                raise ConfigError(f"episodes values must be >= 1 in {block_ctx}")
            pairs.add((season, number))
    return frozenset(pairs)


def _parse_series(raw: Any, index: int) -> DropoutSeries:
    context = f"series[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"Series entry must be a mapping in {context}")
    name = _require_str(raw, "name", context)
    path = _require_str(raw, "path", context)
    has_urls = "urls" in raw
    if has_urls and ("url" in raw or "seasons" in raw):
        raise ConfigError(f"Series {name!r} cannot mix urls with url/seasons")
    if has_urls:
        urls_raw = raw.get("urls")
        if not isinstance(urls_raw, list):
            raise ConfigError(f"urls must be a list in {context}")
        sources = tuple(
            _parse_source_item(item, name, i) for i, item in enumerate(urls_raw, start=1)
        )
    elif "url" in raw or "seasons" in raw:
        seasons_raw = raw.get("seasons") or []
        if not isinstance(seasons_raw, list):
            raise ConfigError(f"seasons must be a list in {context}")
        seasons = tuple(_parse_season(item, name, i) for i, item in enumerate(seasons_raw, start=1))
        sources = (DropoutSource(url=_optional_url(raw.get("url")), seasons=seasons),)
        if sources[0].seasons:
            _validate_source_urls(sources[0], name)
    else:
        sources = ()
    tvdb_id_raw = raw.get("tvdb_id")
    tvdb_id = None
    if tvdb_id_raw is not None:
        tvdb_id = _int_field(tvdb_id_raw, "tvdb_id", context)
        if tvdb_id < 1:
            raise ConfigError(f"tvdb_id must be >= 1 in {context}")
    return DropoutSeries(
        name=name,
        path=path,
        sources=sources,
        tvdb_id=tvdb_id,
        tvdb_skip=_parse_tvdb_skip(raw.get("tvdb_skip"), context),
    )


def season_page_url(source: DropoutSource, season: DropoutSeason) -> str:
    if season.url:
        return season.url.rstrip("/")
    assert source.url is not None and season.dropout is not None
    return f"{source.url.rstrip('/')}/season:{season.dropout}"


def merge_series_by_path(series_list: Sequence[DropoutSeries]) -> tuple[DropoutSeries, ...]:
    order: list[str] = []
    groups: dict[str, list[DropoutSeries]] = {}
    for series in series_list:
        key = series.path.casefold()
        if key not in groups:
            order.append(key)
        groups.setdefault(key, []).append(series)
    merged: list[DropoutSeries] = []
    for key in order:
        items = groups[key]
        if len(items) == 1:
            merged.append(items[0])
            continue
        sources = tuple(source for item in items for source in item.sources)
        skips: set[tuple[int, int]] = set()
        for item in items:
            skips.update(item.tvdb_skip)
        ids = {item.tvdb_id for item in items if item.tvdb_id is not None}
        if len(ids) > 1:
            raise ConfigError(
                f"Conflicting tvdb_id values for path {items[0].path!r}: "
                + ", ".join(str(value) for value in sorted(ids))
            )
        merged.append(
            DropoutSeries(
                name=items[0].name,
                path=items[0].path,
                sources=sources,
                tvdb_id=next(iter(ids), None),
                tvdb_skip=frozenset(skips),
            )
        )
    return tuple(merged)


def _parse_imports_list(raw: Any) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError("imports must be a list of paths")
    if not raw:
        return ()
    paths: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError("imports entries must be non-empty strings")
        paths.append(item.strip())
    return tuple(paths)


def _load_yaml_mapping(path: Path) -> Any:
    if not path.is_file():
        raise ConfigError(f"Import file not found: {path}")
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(format_yaml_error(exc)) from exc


def parse_dropout_series_file(data: Any, path: Path) -> tuple[DropoutSeries, ...]:
    if not isinstance(data, dict):
        raise ConfigError(f"Imported manifest must be a mapping: {path}")
    extra = sorted(key for key in CHILD_FORBIDDEN_KEYS if key in data)
    if extra:
        raise ConfigError(f"Imported file {path} cannot include {', '.join(extra)}")
    series_raw = data.get("series") or []
    if not isinstance(series_raw, list) or not series_raw:
        raise ConfigError(f"Imported file {path} needs a non-empty series list")
    return tuple(_parse_series(item, i) for i, item in enumerate(series_raw, start=1))


def parse_dropout_manifest(
    data: Any,
    path: Path,
    *,
    load_imports: bool = True,
) -> DropoutManifest:
    if not isinstance(data, dict):
        raise ConfigError(f"Dropout manifest must be a mapping: {path}")
    library = _optional_str_path(data.get("library"), "library", str(path))
    old_dir = _optional_str_path(data.get("old_dir"), "old_dir", str(path))
    import_paths = _parse_imports_list(data.get("imports"))
    series_raw = data.get("series")
    if series_raw is None:
        series_raw = []
    if not isinstance(series_raw, list):
        raise ConfigError("series must be a list")
    if not import_paths and not series_raw:
        raise ConfigError("Manifest needs series or imports")
    collected: list[DropoutSeries] = []
    if load_imports:
        for rel in import_paths:
            child_path = Path(rel)
            if not child_path.is_absolute():
                child_path = path.parent / child_path
            collected.extend(parse_dropout_series_file(_load_yaml_mapping(child_path), child_path))
    collected.extend(_parse_series(item, i) for i, item in enumerate(series_raw, start=1))
    if not collected and (load_imports or not import_paths):
        raise ConfigError("Manifest needs series or imports")
    cookies = _optional_path(data.get("cookies"))
    if cookies is not None and not cookies.is_absolute():
        cookies = path.parent / cookies
    if cookies is not None and not cookies.is_file():
        raise ConfigError(f"Cookies file not found: {cookies}")
    if cookies is not None and not cookies_file_usable(cookies):
        raise ConfigError(f"Cookies file is empty: {cookies}")
    staging = data.get("staging")
    if staging is not None and staging != "":
        staging_path = _optional_str_path(staging, "staging", str(path))
    else:
        staging_path = None
    return DropoutManifest(
        library=library,
        old_dir=old_dir,
        series=merge_series_by_path(collected),
        staging=staging_path,
        cookies=cookies,
        path=path,
        imports=import_paths,
    )


def load_dropout_manifest(path: Path) -> DropoutManifest:
    if not path.is_file():
        raise ConfigError(f"Dropout manifest not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(format_yaml_error(exc)) from exc
    return parse_dropout_manifest(data, path)


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
        if not seasons:
            kept.append(series)
            continue
        sources: list[DropoutSource] = []
        for source in series.sources:
            selected = tuple(
                season
                for season in source.seasons
                if season.enabled
                and season.dropout is not None
                and season.dropout in seasons
            )
            if selected:
                sources.append(replace(source, seasons=selected))
        if not sources:
            continue
        kept.append(replace(series, sources=tuple(sources)))
    if not kept:
        raise ConfigError("No series/seasons matched --series/--season")
    return replace(manifest, series=tuple(kept))
