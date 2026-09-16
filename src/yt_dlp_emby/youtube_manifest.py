"""Load and validate a YouTube YAML manifest."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Sequence

import yaml

from yt_dlp_emby.config import ConfigError, format_yaml_error
from yt_dlp_emby.cookies import cookies_file_usable

__all__ = [
    "CHILD_FORBIDDEN_KEYS",
    "YoutubeManifest",
    "YoutubePlaylist",
    "YoutubeSeries",
    "parse_youtube_manifest",
    "parse_youtube_series_file",
    "load_youtube_manifest",
    "filter_youtube_manifest",
]

CHILD_FORBIDDEN_KEYS = frozenset({"library", "old_dir", "cookies", "staging", "imports"})


@dataclass(frozen=True)
class YoutubePlaylist:
    url: str
    season: int | None = None
    enabled: bool = True
    skip: tuple[str, ...] = ()
    title: str | None = None


@dataclass(frozen=True)
class YoutubeSeries:
    name: str
    playlists: tuple[YoutubePlaylist, ...]
    path: str | None = None
    tvdb_id: int | None = None


@dataclass(frozen=True)
class YoutubeManifest:
    library: Path | None = None
    old_dir: Path | None = None
    series: tuple[YoutubeSeries, ...] = ()
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


def _parse_skip_ids(raw: Any, context: str) -> tuple[str, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise ConfigError(f"skip must be a list in {context}")
    ids: list[str] = []
    for item in raw:
        if not isinstance(item, str) or not item.strip():
            raise ConfigError(f"skip entries must be non-empty strings in {context}")
        ids.append(item.strip())
    return tuple(ids)


def _parse_playlist(raw: Any, context: str) -> YoutubePlaylist:
    if not isinstance(raw, dict):
        raise ConfigError(f"Playlist entry must be a mapping in {context}")
    url = _require_str(raw, "url", context)
    season = raw.get("season")
    if season is not None:
        if isinstance(season, bool) or not isinstance(season, int) or season < 1:
            raise ConfigError(f"season must be an integer >= 1 in {context}")
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
    return YoutubePlaylist(
        url=url,
        season=season,
        enabled=enabled,
        skip=_parse_skip_ids(raw.get("skip"), context),
        title=title,
    )


def _parse_series(raw: Any, index: int) -> YoutubeSeries:
    context = f"series[{index}]"
    if not isinstance(raw, dict):
        raise ConfigError(f"Series entry must be a mapping in {context}")
    name = _require_str(raw, "name", context)
    path_raw = raw.get("path")
    path = None
    if path_raw is not None:
        if not isinstance(path_raw, str) or not path_raw.strip():
            raise ConfigError(f"path must be a non-empty string in {context}")
        path = path_raw.strip()
    tvdb_id_raw = raw.get("tvdb_id")
    tvdb_id = None
    if tvdb_id_raw is not None:
        tvdb_id = _int_field(tvdb_id_raw, "tvdb_id", context)
        if tvdb_id < 1:
            raise ConfigError(f"tvdb_id must be >= 1 in {context}")
    playlists_raw = raw.get("playlists")
    if playlists_raw is None:
        playlists_raw = []
    if not isinstance(playlists_raw, list):
        raise ConfigError(f"playlists must be a list in {context}")
    playlists = tuple(
        _parse_playlist(item, f"{context} playlist {i}")
        for i, item in enumerate(playlists_raw, start=1)
    )
    seen: set[str] = set()
    for item in playlists:
        if item.url in seen:
            raise ConfigError(f"Duplicate playlist URL in series {name!r}: {item.url}")
        seen.add(item.url)
    return YoutubeSeries(name=name, playlists=playlists, path=path, tvdb_id=tvdb_id)


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


def parse_youtube_series_file(data: Any, path: Path) -> tuple[YoutubeSeries, ...]:
    if not isinstance(data, dict):
        raise ConfigError(f"Imported manifest must be a mapping: {path}")
    extra = sorted(key for key in CHILD_FORBIDDEN_KEYS if key in data)
    if extra:
        raise ConfigError(f"Imported file {path} cannot include {', '.join(extra)}")
    series_raw = data.get("series") or []
    if not isinstance(series_raw, list) or not series_raw:
        raise ConfigError(f"Imported file {path} needs a non-empty series list")
    return tuple(_parse_series(item, i) for i, item in enumerate(series_raw, start=1))


def parse_youtube_manifest(
    data: Any,
    path: Path,
    *,
    load_imports: bool = True,
) -> YoutubeManifest:
    if not isinstance(data, dict):
        raise ConfigError(f"YouTube manifest must be a mapping: {path}")
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
    collected: list[YoutubeSeries] = []
    if load_imports:
        for rel in import_paths:
            child_path = Path(rel)
            if not child_path.is_absolute():
                child_path = path.parent / child_path
            collected.extend(parse_youtube_series_file(_load_yaml_mapping(child_path), child_path))
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
    return YoutubeManifest(
        library=library,
        old_dir=old_dir,
        series=tuple(collected),
        staging=staging_path,
        cookies=cookies,
        path=path,
        imports=import_paths,
    )


def load_youtube_manifest(path: Path) -> YoutubeManifest:
    if not path.is_file():
        raise ConfigError(f"YouTube manifest not found: {path}")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(format_yaml_error(exc)) from exc
    return parse_youtube_manifest(data, path)


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
