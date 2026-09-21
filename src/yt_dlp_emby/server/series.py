"""Structured series API (no merge by path)."""

from __future__ import annotations

import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FuturesTimeoutError
from pathlib import Path
from typing import Any, Mapping

import yaml

from yt_dlp_emby.config import (
    ConfigError,
    config_target_path,
    describe_manifest_paths,
    env_value,
    format_yaml_error,
    load_config_values,
)
from yt_dlp_emby.cookies import (
    DEFAULT_COOKIE_FILES,
    confined_cookie_path,
    cookies_file_usable,
    inspect_cookie_jars,
)
from yt_dlp_emby.dropout_manifest import (
    DropoutRemap,
    DropoutSeason,
    DropoutSeries,
    DropoutSource,
    parse_dropout_series_file,
)
from yt_dlp_emby.extract import extract_dropout_season, extract_playlist
from yt_dlp_emby.ffmpeg import FFmpegNotFoundError
from yt_dlp_emby.library import series_library_path, series_relpath
from yt_dlp_emby.series_ids import slugify, unique_slug
from yt_dlp_emby.server.manifests import (
    _confined_import_path,
    _manifest_path,
    atomic_write_manifest_text,
)
from yt_dlp_emby.server.series_discover import (
    ChannelDiscoverError,
    discover_dropout_source,
    discover_youtube_sources,
    dropout_episode_rows,
    merge_dropout_seasons,
    sanitize_discovery_message,
    youtube_episode_rows,
)
from yt_dlp_emby.youtube_manifest import (
    YoutubePlaylist,
    YoutubeSeries,
    parse_youtube_series_file,
)

PLATFORMS = frozenset({"youtube", "dropout"})

logger = logging.getLogger("yt_dlp_emby.server")

# Per-series cap for batch refresh: one slow listing must not stall the rest.
REFRESH_ITEM_TIMEOUT_SECONDS = 60.0

# Poster cache freshness: after this age the cached file is refetched (the
# stale bytes are still served if the refetch fails).
POSTER_CACHE_TTL_SECONDS = 24 * 3600

# Absolute paths at / under these roots are rejected unless ALLOW_ROOT_PATHS=1.
_DENIED_FS_PREFIXES = ("/etc", "/root", "/proc", "/sys", "/dev")


def _allow_root_paths(environ: Mapping[str, str]) -> bool:
    return str(environ.get("ALLOW_ROOT_PATHS") or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def validate_fs_dir_path(
    value: str | None,
    name: str,
    *,
    data_dir: Path,
    environ: Mapping[str, str],
) -> Path | None:
    """Validate a user-supplied directory path (library/old_dir/staging/...).

    Returns the resolved path, or None when empty (meaning "clear"). Raises
    ValueError when the path escapes, points at a denied system root, exists
    as a non-directory, or cannot be created. Missing directories are created
    with mode 0700 (only newly created dirs are chmodded; existing user
    libraries are left untouched).
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if ".." in Path(text).parts:
        raise ValueError(f"{name} must not contain '..'")
    candidate = Path(text)
    if candidate.is_absolute():
        resolved = candidate.resolve()
    else:
        base = data_dir.resolve()
        resolved = (data_dir / text).resolve()
        if not resolved.is_relative_to(base):
            raise ValueError(f"{name} must stay within the data directory")
    if not _allow_root_paths(environ):
        posix = resolved.as_posix()
        if posix == "/":
            raise ValueError(f"{name} must not be '/' (set ALLOW_ROOT_PATHS=1 to override)")
        for denied in _DENIED_FS_PREFIXES:
            if posix == denied or posix.startswith(denied + "/"):
                raise ValueError(
                    f"{name} must not point inside {denied} (set ALLOW_ROOT_PATHS=1 to override)"
                )
    if resolved.exists() or resolved.is_symlink():
        if not resolved.is_dir():
            raise ValueError(f"{name} exists and is not a directory")
        return resolved
    try:
        resolved.mkdir(parents=True, mode=0o700, exist_ok=True)
        try:
            os.chmod(resolved, 0o700)
        except OSError:
            pass
    except OSError as exc:
        raise ValueError(f"{name} is not a usable directory: {exc}") from exc
    return resolved


def validate_cookie_filename(value: str | None, *, data_dir: Path) -> str | None:
    """Validate a manifest `cookies` field: a data-dir-relative file path."""
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    candidate = Path(text)
    if candidate.is_absolute() or ".." in candidate.parts:
        raise ValueError("cookies must be a data-dir-relative path without '..'")
    resolved = (data_dir / text).resolve()
    if not resolved.is_relative_to(data_dir.resolve()):
        raise ValueError("cookies must stay within the data directory")
    return text


class SeriesError(ValueError):
    """Base class for series API errors."""


class SeriesExistsError(SeriesError):
    """A series name, path, or slug is already in use."""


class AmbiguousSlugError(SeriesError):
    """Multiple series files claim the same slug (maps to HTTP 409)."""


class SeriesValidationError(SeriesError):
    """A series payload failed semantic validation (maps to HTTP 400)."""


class SeriesNotFoundError(KeyError):
    """No series matched the given platform/slug."""


def series_poster_url(platform: str, slug: str, stamp: str | None = None) -> str:
    url = f"/api/series/{platform}/{slug}/poster"
    if stamp:
        from urllib.parse import quote

        return f"{url}?t={quote(stamp, safe='')}"
    return url


def _decorate_series(data_dir: Path, detail: dict[str, Any]) -> dict[str, Any]:
    from yt_dlp_emby.server.refresh_stamp import series_refresh_payload

    refreshed = series_refresh_payload(data_dir, detail["platform"], detail["slug"])
    stamp = refreshed.get("sonarr") or refreshed.get("listings") or refreshed.get("disk")
    detail["refreshed"] = refreshed
    detail["poster_url"] = series_poster_url(
        detail["platform"], detail["slug"], stamp if isinstance(stamp, str) else None
    )
    return detail


def _try_patch_plan(
    data_dir: Path,
    platform: str,
    slug: str,
    environ: Mapping[str, str] | None,
) -> None:
    if environ is None:
        return
    try:
        from yt_dlp_emby.server.plan_series import patch_series_plan

        patch_series_plan(data_dir, platform, slug, environ=environ)
    except Exception as exc:
        logger.debug("plan patch for %s|%s failed: %s", platform, slug, exc)
        return


def resolve_shows_dir(data_dir: Path, environ: Mapping[str, str]) -> Path:
    config_path = config_target_path(None, environ, data_dir)
    values = load_config_values(config_path) if config_path.is_file() else {}
    raw = env_value(environ, "SHOWS_DIR") or values.get("shows_dir") or "shows"
    if ".." in Path(raw).parts:
        raise ValueError("shows_dir escapes data directory")
    resolved = (data_dir / raw).resolve()
    if not resolved.is_relative_to(data_dir.resolve()):
        raise ValueError("shows_dir escapes data directory")
    return resolved


def _assign_slug(
    name: str,
    used: set[str],
    *,
    file_stem: str | None = None,
    series_count: int = 1,
) -> str:
    if file_stem and series_count == 1 and file_stem not in used:
        used.add(file_stem)
        return file_stem
    slug = unique_slug(name, used)
    used.add(slug)
    return slug


def _slug_for_file(series_count: int, file_stem: str, name: str) -> str:
    if series_count == 1:
        return file_stem
    return slugify(name)


class SeriesLocator:
    def __init__(
        self,
        platform: str,
        slug: str,
        file: str,
        inline: bool,
        index: int,
    ) -> None:
        self.platform = platform
        self.slug = slug
        self.file = file
        self.inline = inline
        self.index = index


def _load_root_yaml(data_dir: Path, platform: str) -> tuple[dict[str, Any], Path]:
    path = _manifest_path(data_dir, platform)
    if not path.is_file():
        return {}, path
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(format_yaml_error(exc)) from exc
    if not isinstance(data, dict):
        return {}, path
    return data, path


def _imports_from_data(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("imports")
    if not isinstance(raw, list):
        return ()
    return tuple(item.strip() for item in raw if isinstance(item, str) and item.strip())


def _record_load_error(errors: list[dict[str, str]] | None, file: str, exc: BaseException) -> None:
    if errors is None:
        return
    message = format_yaml_error(exc) if isinstance(exc, yaml.YAMLError) else str(exc)
    errors.append({"file": file, "error": message})


def _iter_dropout_entries(
    data_dir: Path, *, errors: list[dict[str, str]] | None = None
) -> list[tuple[SeriesLocator, DropoutSeries]]:
    out: list[tuple[SeriesLocator, DropoutSeries]] = []
    try:
        data, root_path = _load_root_yaml(data_dir, "dropout")
    except ConfigError as exc:
        _record_load_error(errors, "dropout.yaml", exc)
        return out
    if data:
        inline: tuple[DropoutSeries, ...] = ()
        series_raw = data.get("series") or []
        if series_raw:
            try:
                inline = parse_dropout_series_file({"series": series_raw}, root_path)
            except ConfigError as exc:
                _record_load_error(errors, "dropout.yaml", exc)
        for rel in _imports_from_data(data):
            confined = _confined_import_path(data_dir, rel)
            if confined is None:
                _record_load_error(
                    errors, rel, ConfigError(f"Import path escapes data directory: {rel}")
                )
                continue
            if not confined.is_file():
                _record_load_error(errors, rel, ConfigError(f"Import file not found: {rel}"))
                continue
            try:
                items = parse_dropout_series_file(
                    yaml.safe_load(confined.read_text(encoding="utf-8")),
                    confined,
                )
            except (ConfigError, yaml.YAMLError) as exc:
                _record_load_error(errors, rel, exc)
                continue
            stem = confined.stem
            for j, series in enumerate(items):
                used = {loc.slug for loc, _s in out}
                slug = _assign_slug(series.name, used, file_stem=stem, series_count=len(items))
                rel_path = (
                    str(confined.relative_to(data_dir.resolve()))
                    if confined.is_relative_to(data_dir.resolve())
                    else rel
                )
                out.append(
                    (
                        SeriesLocator("dropout", slug, rel_path, False, j),
                        series,
                    )
                )
        for i, series in enumerate(inline):
            slug = unique_slug(series.name, {loc.slug for loc, _s in out})
            out.append(
                (
                    SeriesLocator("dropout", slug, "dropout.yaml", True, i),
                    series,
                )
            )
    return out


def _iter_youtube_entries(
    data_dir: Path, *, errors: list[dict[str, str]] | None = None
) -> list[tuple[SeriesLocator, YoutubeSeries]]:
    out: list[tuple[SeriesLocator, YoutubeSeries]] = []
    try:
        data, root_path = _load_root_yaml(data_dir, "youtube")
    except ConfigError as exc:
        _record_load_error(errors, "youtube.yaml", exc)
        return out
    if data:
        inline: tuple[YoutubeSeries, ...] = ()
        series_raw = data.get("series") or []
        if series_raw:
            try:
                inline = parse_youtube_series_file({"series": series_raw}, root_path)
            except ConfigError as exc:
                _record_load_error(errors, "youtube.yaml", exc)
        for rel in _imports_from_data(data):
            confined = _confined_import_path(data_dir, rel)
            if confined is None:
                _record_load_error(
                    errors, rel, ConfigError(f"Import path escapes data directory: {rel}")
                )
                continue
            if not confined.is_file():
                _record_load_error(errors, rel, ConfigError(f"Import file not found: {rel}"))
                continue
            try:
                items = parse_youtube_series_file(
                    yaml.safe_load(confined.read_text(encoding="utf-8")),
                    confined,
                )
            except (ConfigError, yaml.YAMLError) as exc:
                _record_load_error(errors, rel, exc)
                continue
            stem = confined.stem
            for j, series in enumerate(items):
                used = {loc.slug for loc, _s in out}
                slug = _assign_slug(series.name, used, file_stem=stem, series_count=len(items))
                rel_path = (
                    str(confined.relative_to(data_dir.resolve()))
                    if confined.is_relative_to(data_dir.resolve())
                    else rel
                )
                out.append(
                    (
                        SeriesLocator("youtube", slug, rel_path, False, j),
                        series,
                    )
                )
        for i, series in enumerate(inline):
            slug = unique_slug(series.name, {loc.slug for loc, _s in out})
            out.append(
                (
                    SeriesLocator("youtube", slug, "youtube.yaml", True, i),
                    series,
                )
            )
    return out


def _find_locator(
    data_dir: Path, platform: str, slug: str
) -> tuple[SeriesLocator, DropoutSeries | YoutubeSeries]:
    if platform not in PLATFORMS:
        raise KeyError(slug)
    slug_cf = slug.casefold()
    entries: list[tuple[SeriesLocator, Any]]
    if platform == "dropout":
        entries = _iter_dropout_entries(data_dir)
    else:
        entries = _iter_youtube_entries(data_dir)
    matches = [(loc, s) for loc, s in entries if loc.slug.casefold() == slug_cf]
    if not matches:
        raise KeyError(slug)
    imported = [item for item in matches if not item[0].inline]
    if imported:
        if len(imported) > 1:
            raise AmbiguousSlugError(f"ambiguous slug {slug}")
        return imported[0]
    if len(matches) > 1:
        raise AmbiguousSlugError(f"ambiguous slug {slug}")
    return matches[0]


def locate_series(
    data_dir: Path, platform: str, slug: str
) -> tuple[SeriesLocator, DropoutSeries | YoutubeSeries]:
    """Resolve a series by locator slug or slugify(name) (plan vs file-stem)."""
    try:
        return _find_locator(data_dir, platform, slug)
    except KeyError:
        pass
    if platform not in PLATFORMS:
        raise KeyError(slug)
    wanted = slug.casefold()
    entries: list[tuple[SeriesLocator, Any]] = (
        _iter_dropout_entries(data_dir)
        if platform == "dropout"
        else _iter_youtube_entries(data_dir)
    )
    matches = [
        (loc, series)
        for loc, series in entries
        if wanted in {loc.slug.casefold(), slugify(series.name)}
    ]
    if not matches:
        raise KeyError(slug)
    imported = [item for item in matches if not item[0].inline]
    pool = imported or matches
    if len(pool) > 1:
        raise AmbiguousSlugError(f"ambiguous slug {slug}")
    return pool[0]


def series_folder_rel(series: DropoutSeries | YoutubeSeries) -> str:
    return getattr(series, "path", None) or series.name


def _season_label(
    to_season: int | None,
    dropout: int | None,
    title: str | None = None,
) -> tuple[str, str]:
    if to_season == 0:
        sub = "Specials"
    elif to_season is not None:
        sub = f"Season {to_season}"
    else:
        sub = ""
    if title:
        extra = f"Dropout {dropout}" if dropout is not None else ""
        if extra and sub:
            return title, f"{sub} · {extra}"
        return title, sub or extra
    if to_season == 0:
        return "Specials", f"Dropout {dropout}" if dropout is not None else ""
    if to_season is not None:
        extra = f"Dropout {dropout}" if dropout is not None else ""
        return f"Season {to_season}", extra
    if dropout is not None:
        return f"Dropout season {dropout}", ""
    return "Season", ""


def _remap_to_dict(r: DropoutRemap) -> dict[str, Any]:
    if r.skip:
        return {"dropout_episode": r.dropout_episode, "skip": True}
    return {
        "dropout_episode": r.dropout_episode,
        "to_season": r.to_season,
        "to_episode": r.to_episode,
        "title": r.title,
    }


def _dropout_series_to_detail(
    loc: SeriesLocator,
    series: DropoutSeries,
    *,
    errors: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for sid, source in enumerate(series.sources):
        seasons: list[dict[str, Any]] = []
        for seid, season in enumerate(source.seasons):
            to_season = season.to_season
            display = to_season if to_season is not None else season.dropout
            label, sublabel = _season_label(display, season.dropout, season.title)
            seasons.append(
                {
                    "id": str(seid),
                    "dropout": season.dropout,
                    "url": season.url,
                    "to_season": to_season,
                    "enabled": season.enabled,
                    "title": season.title,
                    "only_episodes": list(season.only_episodes) if season.only_episodes else None,
                    "remaps": [_remap_to_dict(r) for r in season.remap],
                    "skip_ids": [],
                    "label": label,
                    "sublabel": sublabel,
                }
            )
        sources.append(
            {
                "id": str(sid),
                "url": source.url or "",
                "error": (errors or {}).get(sid),
                "seasons": seasons,
            }
        )
    tvdb_skip = [
        {"season": s, "episodes": sorted(e for ss, e in series.tvdb_skip if ss == s)}
        for s in sorted({pair[0] for pair in series.tvdb_skip})
    ]
    for block in tvdb_skip:
        block["episodes"] = sorted(e for ss, e in series.tvdb_skip if ss == block["season"])
    enabled_seasons = sum(1 for src in series.sources for se in src.seasons if se.enabled)
    return {
        "platform": loc.platform,
        "slug": loc.slug,
        "file": loc.file,
        "inline": loc.inline,
        "name": series.name,
        "path": series.path,
        "tvdb_id": series.tvdb_id,
        "source_count": len(series.sources),
        "season_count": enabled_seasons,
        "tvdb_skip": tvdb_skip,
        "sources": sources,
        "poster_url": series_poster_url(loc.platform, loc.slug),
    }


def _youtube_series_to_detail(
    loc: SeriesLocator,
    series: YoutubeSeries,
    *,
    errors: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for sid, pl in enumerate(series.playlists):
        to_season = pl.season
        display = to_season if to_season is not None else sid + 1
        label, sublabel = _season_label(display, None, pl.title)
        sources.append(
            {
                "id": str(sid),
                "url": pl.url,
                "error": (errors or {}).get(sid),
                "seasons": [
                    {
                        "id": "0",
                        "dropout": None,
                        "url": pl.url,
                        "to_season": to_season,
                        "enabled": pl.enabled,
                        "title": pl.title,
                        "only_episodes": None,
                        "remaps": [],
                        "skip_ids": list(pl.skip),
                        "label": label,
                        "sublabel": sublabel,
                    }
                ],
            }
        )
    enabled = sum(1 for pl in series.playlists if pl.enabled)
    return {
        "platform": loc.platform,
        "slug": loc.slug,
        "file": loc.file,
        "inline": loc.inline,
        "name": series.name,
        "path": series.path or series.name,
        "tvdb_id": series.tvdb_id,
        "source_count": len(series.playlists),
        "season_count": enabled,
        "tvdb_skip": [],
        "sources": sources,
        "poster_url": series_poster_url(loc.platform, loc.slug),
    }


def list_series(data_dir: Path, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    env = environ or {}
    items: list[dict[str, Any]] = []
    import_errors: list[dict[str, str]] = []
    dropout_cache = _dropout_listing_cache(data_dir)
    for loc, series in _iter_dropout_entries(data_dir, errors=import_errors):
        detail = _dropout_series_to_detail(loc, series)
        items.append(
            {
                "platform": detail["platform"],
                "slug": detail["slug"],
                "file": detail["file"],
                "inline": detail["inline"],
                "name": detail["name"],
                "path": detail["path"],
                "tvdb_id": detail["tvdb_id"],
                "source_count": detail["source_count"],
                "season_count": detail["season_count"],
                "missing_count": _dropout_missing_count(data_dir, series, env, cache=dropout_cache),
                "listings_complete": _dropout_listings_complete(series, dropout_cache),
            }
        )
        items[-1] = _decorate_series(data_dir, items[-1])
    from yt_dlp_emby.server.plan_series import plan_pending_for_slug

    for loc, yt_series in _iter_youtube_entries(data_dir, errors=import_errors):
        detail = _youtube_series_to_detail(loc, yt_series)
        items.append(
            {
                "platform": detail["platform"],
                "slug": detail["slug"],
                "file": detail["file"],
                "inline": detail["inline"],
                "name": detail["name"],
                "path": detail["path"],
                "tvdb_id": detail["tvdb_id"],
                "source_count": detail["source_count"],
                "season_count": detail["season_count"],
                "missing_count": plan_pending_for_slug(
                    data_dir, "youtube", detail["slug"], environ=env
                ),
                "listings_complete": False,
            }
        )
        items[-1] = _decorate_series(data_dir, items[-1])
    items.sort(key=lambda row: row["name"].casefold())
    return {"series": items, "import_errors": import_errors}


def get_series(data_dir: Path, platform: str, slug: str) -> dict[str, Any]:
    loc, series = _find_locator(data_dir, platform, slug)
    if platform == "dropout":
        assert isinstance(series, DropoutSeries)
        detail = _dropout_series_to_detail(loc, series)
    else:
        assert isinstance(series, YoutubeSeries)
        detail = _youtube_series_to_detail(loc, series)
    return _decorate_series(data_dir, detail)


def _all_names(data_dir: Path) -> set[str]:
    names: set[str] = set()
    entry: DropoutSeries | YoutubeSeries
    for _, entry in _iter_dropout_entries(data_dir):
        names.add(entry.name.casefold())
    for _, entry in _iter_youtube_entries(data_dir):
        names.add(entry.name.casefold())
    return names


def _paths_for_platform(data_dir: Path, platform: str) -> set[str]:
    paths: set[str] = set()
    entry: DropoutSeries | YoutubeSeries
    if platform == "dropout":
        for _, entry in _iter_dropout_entries(data_dir):
            if entry.path:
                paths.add(entry.path.casefold())
    else:
        for _, entry in _iter_youtube_entries(data_dir):
            p = entry.path or entry.name
            paths.add(p.casefold())
    return paths


def _append_import(data_dir: Path, platform: str, rel_import: str) -> None:
    data, path = _load_root_yaml(data_dir, platform)
    created_from_example = False
    if not data and not path.is_file():
        example = Path(__file__).parent / "examples" / f"{platform}.yaml.example"
        data = yaml.safe_load(example.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            data = {}
        created_from_example = True
    if created_from_example:
        data["series"] = []
        imports = [rel_import]
    else:
        imports = list(data.get("imports") or [])
        if rel_import not in imports:
            imports.append(rel_import)
    data["imports"] = imports
    if "series" not in data:
        data["series"] = []
    _dump_yaml(path, data)


def _write_child_dropout(path: Path, series: DropoutSeries) -> None:
    _dump_yaml(path, {"series": [_dropout_series_to_yaml(series)]})


def _write_child_youtube(path: Path, series: YoutubeSeries) -> None:
    _dump_yaml(path, {"series": [_youtube_series_to_yaml(series)]})


def _dropout_series_to_yaml(series: DropoutSeries) -> dict[str, Any]:
    block: dict[str, Any] = {"name": series.name, "path": series.path}
    if series.tvdb_id is not None:
        block["tvdb_id"] = series.tvdb_id
    if series.tvdb_skip:
        by_season: dict[int, list[int]] = {}
        for s, e in sorted(series.tvdb_skip):
            by_season.setdefault(s, []).append(e)
        block["tvdb_skip"] = [
            {"season": s, "episodes": eps} for s, eps in sorted(by_season.items())
        ]
    if not series.sources:
        return block
    if len(series.sources) == 1 and series.sources[0].url and len(series.sources) == 1:
        src = series.sources[0]
        block["url"] = src.url
        block["seasons"] = [_dropout_season_to_yaml(se) for se in src.seasons]
        return block
    block["urls"] = []
    for src in series.sources:
        item: dict[str, Any] = {"seasons": [_dropout_season_to_yaml(se) for se in src.seasons]}
        if src.url:
            item["url"] = src.url
        block["urls"].append(item)
    return block


def _dropout_season_to_yaml(season: DropoutSeason) -> dict[str, Any]:
    out: dict[str, Any] = {}
    if season.dropout is not None:
        out["dropout"] = season.dropout
    if season.url:
        out["url"] = season.url
    if season.to_season is not None:
        out["to_season"] = season.to_season
    if not season.enabled:
        out["enabled"] = False
    if season.only_episodes:
        out["only_episodes"] = list(season.only_episodes)
    if season.remap:
        out["remap"] = [_remap_to_dict(r) for r in season.remap]
    if season.title:
        out["title"] = season.title
    return out


def _youtube_series_to_yaml(series: YoutubeSeries) -> dict[str, Any]:
    block: dict[str, Any] = {"name": series.name}
    if series.path:
        block["path"] = series.path
    if series.tvdb_id is not None:
        block["tvdb_id"] = series.tvdb_id
    playlists = []
    for pl in series.playlists:
        item: dict[str, Any] = {"url": pl.url}
        if pl.season is not None:
            item["season"] = pl.season
        if not pl.enabled:
            item["enabled"] = False
        if pl.title:
            item["title"] = pl.title
        if pl.skip:
            item["skip"] = list(pl.skip)
        playlists.append(item)
    if playlists:
        block["playlists"] = playlists
    return block


def create_series(
    data_dir: Path,
    environ: Mapping[str, str],
    *,
    name: str,
    platform: str,
    path: str,
    tvdb_id: int | None,
) -> dict[str, Any]:
    if platform not in PLATFORMS:
        raise SeriesValidationError("unknown platform")
    name = name.strip()
    path = series_relpath(path.strip())
    slug = slugify(name)
    if not slug:
        raise SeriesValidationError("invalid title for slug")
    if name.casefold() in _all_names(data_dir):
        raise SeriesExistsError(f"A series named {name} already exists")
    if path.casefold() in _paths_for_platform(data_dir, platform):
        raise SeriesExistsError(f"A series with folder {path} already exists on {platform}")
    shows = resolve_shows_dir(data_dir, environ)
    child = shows / f"{slug}.yaml"
    if child.exists():
        raise SeriesExistsError("slug already exists")
    series: DropoutSeries | YoutubeSeries
    if platform == "dropout":
        series = DropoutSeries(name=name, path=path, sources=(), tvdb_id=tvdb_id)
        _write_child_dropout(child, series)
    else:
        series = YoutubeSeries(name=name, playlists=(), path=path, tvdb_id=tvdb_id)
        _write_child_youtube(child, series)
    rel = str(child.relative_to(data_dir.resolve()))
    _append_import(data_dir, platform, rel)
    loc = SeriesLocator(platform, child.stem, rel, False, 0)
    if platform == "dropout":
        assert isinstance(series, DropoutSeries)
        return _dropout_series_to_detail(loc, series)
    assert isinstance(series, YoutubeSeries)
    return _youtube_series_to_detail(loc, series)


def _detail_to_dropout(body: dict[str, Any]) -> DropoutSeries:
    sources: list[DropoutSource] = []
    for src in body.get("sources") or []:
        seasons: list[DropoutSeason] = []
        for se in src.get("seasons") or []:
            remaps: list[DropoutRemap] = []
            for raw in se.get("remaps") or []:
                if raw.get("skip"):
                    remaps.append(
                        DropoutRemap(dropout_episode=int(raw["dropout_episode"]), skip=True)
                    )
                else:
                    remaps.append(
                        DropoutRemap(
                            dropout_episode=int(raw["dropout_episode"]),
                            to_season=int(raw["to_season"]),
                            to_episode=int(raw["to_episode"]),
                            title=raw.get("title"),
                        )
                    )
            only = se.get("only_episodes")
            if only is None:
                only_t = None
            else:
                only_t = tuple(int(x) for x in only) if only else ()
            title_raw = se.get("title")
            title = None
            if title_raw is not None:
                title = str(title_raw).strip() or None
            seasons.append(
                DropoutSeason(
                    dropout=se.get("dropout"),
                    url=se.get("url"),
                    to_season=se.get("to_season"),
                    remap=tuple(remaps),
                    only_episodes=only_t,
                    enabled=bool(se.get("enabled", True)),
                    title=title,
                )
            )
        sources.append(DropoutSource(url=src.get("url") or None, seasons=tuple(seasons)))
    tvdb_skip: set[tuple[int, int]] = set()
    for block in body.get("tvdb_skip") or []:
        season = int(block["season"])
        for ep in block.get("episodes") or []:
            tvdb_skip.add((season, int(ep)))
    tvdb = body.get("tvdb_id")
    return DropoutSeries(
        name=str(body["name"]),
        path=series_relpath(str(body["path"])),
        sources=tuple(sources),
        tvdb_id=int(tvdb) if tvdb is not None else None,
        tvdb_skip=frozenset(tvdb_skip),
    )


def _detail_to_youtube(body: dict[str, Any]) -> YoutubeSeries:
    playlists: list[YoutubePlaylist] = []
    for src in body.get("sources") or []:
        for se in src.get("seasons") or []:
            title_raw = se.get("title")
            title = None
            if title_raw is not None:
                title = str(title_raw).strip() or None
            playlists.append(
                YoutubePlaylist(
                    url=str(src.get("url") or se.get("url")),
                    season=(
                        se.get("to_season")
                        if isinstance(se.get("to_season"), int) and se.get("to_season") >= 1
                        else None
                    ),
                    enabled=bool(se.get("enabled", True)),
                    skip=tuple(str(x) for x in (se.get("skip_ids") or [])),
                    title=title,
                )
            )
    tvdb = body.get("tvdb_id")
    path_raw = str(body.get("path") or body["name"])
    return YoutubeSeries(
        name=str(body["name"]),
        playlists=tuple(playlists),
        path=series_relpath(path_raw),
        tvdb_id=int(tvdb) if tvdb is not None else None,
    )


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    from io import StringIO

    from ruamel.yaml import YAML

    from yt_dlp_emby.cache import file_lock

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 4096
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    with file_lock(path):
        existing: Any = None
        if path.is_file():
            try:
                existing = yaml_rt.load(path.read_text(encoding="utf-8"))
            except Exception as exc:
                logger.debug("comment-preserving YAML merge skipped for %s: %s", path, exc)
                existing = None
        if isinstance(existing, dict):
            for key, value in data.items():
                existing[key] = value
            payload = existing
        else:
            payload = data
        buf = StringIO()
        yaml_rt.dump(payload, buf)
        atomic_write_manifest_text(path, buf.getvalue())


def _cookie_path_for_platform(data_dir: Path, platform: str, environ: Mapping[str, str]) -> Path:
    jars = inspect_cookie_jars(data_dir, environ)
    if jars.get("env_set"):
        env_path = jars.get("env_path")
        if env_path:
            path = Path(str(env_path))
            if path.is_file() and cookies_file_usable(path):
                return path
            raise ConfigError(f"Cookies file not found: {env_path}")
    data, _ = _load_root_yaml(data_dir, platform)
    field = str((data.get("cookies") if data else None) or "").strip()
    confined = confined_cookie_path(data_dir, field or None)
    if confined is not None:
        if confined.is_file() and cookies_file_usable(confined):
            return confined
        raise ConfigError(f"Cookies file not found: {field}")
    default_name = DEFAULT_COOKIE_FILES.get(platform, "cookies.txt")
    path = data_dir / default_name
    if path.is_file() and cookies_file_usable(path):
        return path
    raise ConfigError(f"Cookies file not found: {default_name}")


def _remove_import(data_dir: Path, platform: str, rel_import: str) -> None:
    data, path = _load_root_yaml(data_dir, platform)
    if not data:
        return
    imports = [item for item in _imports_from_data(data) if item != rel_import]
    data["imports"] = imports
    _dump_yaml(path, data)


def _items_from_raw(platform: str, raw: dict[str, Any], path: Path) -> list[Any]:
    series_only = {"series": raw.get("series") or []}
    if platform == "dropout":
        return list(parse_dropout_series_file(series_only, path))
    return list(parse_youtube_series_file(series_only, path))


def _save_locator_series(
    data_dir: Path,
    loc: SeriesLocator,
    series: DropoutSeries | YoutubeSeries,
) -> None:
    confined = _confined_import_path(data_dir, loc.file)
    if confined is None or not confined.is_file():
        raise ValueError("invalid series file path")
    raw = yaml.safe_load(confined.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raw = {}
    items = list(_items_from_raw(loc.platform, raw, confined))
    if loc.index < 0 or loc.index >= len(items):
        raise ValueError("invalid series index")
    items[loc.index] = series
    if loc.platform == "dropout":
        yaml_items = [_dropout_series_to_yaml(s) for s in items]
    else:
        yaml_items = [_youtube_series_to_yaml(s) for s in items]
    if loc.inline:
        raw["series"] = yaml_items
        _dump_yaml(confined, raw)
        return
    _dump_yaml(confined, {"series": yaml_items})


def delete_series(data_dir: Path, platform: str, slug: str) -> None:
    loc, _ = _find_locator(data_dir, platform, slug)
    confined = _confined_import_path(data_dir, loc.file)
    if confined is None:
        raise ValueError("invalid series file path")
    raw = yaml.safe_load(confined.read_text(encoding="utf-8")) if confined.is_file() else {}
    if not isinstance(raw, dict):
        raw = {}
    items = list(_items_from_raw(platform, raw, confined)) if confined.is_file() else []
    if loc.index < 0 or loc.index >= len(items):
        raise KeyError(slug)
    items.pop(loc.index)
    if loc.inline:
        raw["series"] = (
            [_dropout_series_to_yaml(s) for s in items]
            if platform == "dropout"
            else [_youtube_series_to_yaml(s) for s in items]
        )
        _dump_yaml(confined, raw)
        return
    if not items:
        if confined.is_file():
            confined.unlink()
        _remove_import(data_dir, platform, loc.file)
        return
    yaml_items = (
        [_dropout_series_to_yaml(s) for s in items]
        if platform == "dropout"
        else [_youtube_series_to_yaml(s) for s in items]
    )
    _dump_yaml(confined, {"series": yaml_items})


def add_series_source(
    data_dir: Path,
    platform: str,
    slug: str,
    url: str,
    *,
    environ: Mapping[str, str],
    fetch_html=None,
    extract_channel=None,
) -> dict[str, Any]:
    loc, series = _find_locator(data_dir, platform, slug)
    url = url.strip()
    if not url:
        raise ValueError("url is required")
    cookie = str(_cookie_path_for_platform(data_dir, platform, environ))
    source_error: str | None = None
    if platform == "dropout":
        assert isinstance(series, DropoutSeries)
        seasons_raw = discover_dropout_source(url, cookiefile=cookie, fetch_html=fetch_html)
        if not seasons_raw:
            raise ValueError("no seasons found")
        sources = list(series.sources)
        sources.append(
            DropoutSource(
                url=url,
                seasons=tuple(
                    DropoutSeason(
                        dropout=int(s["dropout"]),
                        url=str(s["url"]),
                        to_season=int(s["to_season"]),
                        enabled=bool(s.get("enabled", True)),
                    )
                    for s in seasons_raw
                ),
            )
        )
        series = DropoutSeries(
            name=series.name,
            path=series.path,
            sources=tuple(sources),
            tvdb_id=series.tvdb_id,
            tvdb_skip=series.tvdb_skip,
        )
    else:
        assert isinstance(series, YoutubeSeries)
        playlists = list(series.playlists)
        try:
            discovered = discover_youtube_sources(
                url, cookiefile=cookie, extract_channel=extract_channel
            )
        except ChannelDiscoverError as exc:
            discovered = [
                {
                    "url": url,
                    "seasons": [{"to_season": len(playlists) + 1}],
                }
            ]
            source_error = sanitize_discovery_message(exc.message)
        for src in discovered:
            season = (src.get("seasons") or [{}])[0]
            playlists.append(
                YoutubePlaylist(
                    url=str(src["url"]),
                    season=int(season.get("to_season") or len(playlists) + 1),
                    enabled=True,
                    skip=(),
                )
            )
        series = YoutubeSeries(
            name=series.name,
            playlists=tuple(playlists),
            path=series.path,
            tvdb_id=series.tvdb_id,
        )
    _save_locator_series(data_dir, loc, series)
    detail = get_series(data_dir, platform, slug)
    if source_error and detail.get("sources"):
        detail["sources"][-1]["error"] = source_error
    _try_patch_plan(data_dir, platform, slug, environ)
    return detail


def delete_series_source(
    data_dir: Path,
    platform: str,
    slug: str,
    source_id: int,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    loc, series = _find_locator(data_dir, platform, slug)
    if platform == "dropout":
        assert isinstance(series, DropoutSeries)
        sources = list(series.sources)
        if source_id < 0 or source_id >= len(sources):
            raise KeyError("source")
        sources.pop(source_id)
        series = DropoutSeries(
            name=series.name,
            path=series.path,
            sources=tuple(sources),
            tvdb_id=series.tvdb_id,
            tvdb_skip=series.tvdb_skip,
        )
    else:
        assert isinstance(series, YoutubeSeries)
        playlists = list(series.playlists)
        if source_id < 0 or source_id >= len(playlists):
            raise KeyError("source")
        playlists.pop(source_id)
        series = YoutubeSeries(
            name=series.name,
            playlists=tuple(playlists),
            path=series.path,
            tvdb_id=series.tvdb_id,
        )
    _save_locator_series(data_dir, loc, series)
    _try_patch_plan(data_dir, platform, slug, environ)
    return get_series(data_dir, platform, slug)


def refresh_series_source(
    data_dir: Path,
    platform: str,
    slug: str,
    source_id: int,
    *,
    environ: Mapping[str, str],
    fetch_html=None,
    extract_channel=None,
    patch_plan: bool = True,
) -> dict[str, Any]:
    loc, series = _find_locator(data_dir, platform, slug)
    cookie = str(_cookie_path_for_platform(data_dir, platform, environ))
    source_error: str | None = None
    if platform == "dropout":
        assert isinstance(series, DropoutSeries)
        if source_id < 0 or source_id >= len(series.sources):
            raise KeyError("source")
        source = series.sources[source_id]
        if not source.url:
            raise ValueError("source has no url")
        seasons_raw = discover_dropout_source(source.url, cookiefile=cookie, fetch_html=fetch_html)
        if not seasons_raw:
            raise ValueError("no seasons found")
        merged = merge_dropout_seasons(source.seasons, seasons_raw)
        sources = list(series.sources)
        sources[source_id] = DropoutSource(url=source.url, seasons=merged)
        series = DropoutSeries(
            name=series.name,
            path=series.path,
            sources=tuple(sources),
            tvdb_id=series.tvdb_id,
            tvdb_skip=series.tvdb_skip,
        )
    else:
        assert isinstance(series, YoutubeSeries)
        if source_id < 0 or source_id >= len(series.playlists):
            raise KeyError("source")
        pl = series.playlists[source_id]
        try:
            discovered = discover_youtube_sources(
                pl.url, cookiefile=cookie, extract_channel=extract_channel
            )
        except ChannelDiscoverError as exc:
            discovered = []
            source_error = sanitize_discovery_message(exc.message)
        if not discovered and not source_error:
            raise ValueError("could not refresh playlist")
        season_no = pl.season or (source_id + 1)
        playlists = list(series.playlists)
        playlists[source_id] = YoutubePlaylist(
            url=pl.url,
            season=season_no,
            enabled=pl.enabled,
            skip=pl.skip,
        )
        series = YoutubeSeries(
            name=series.name,
            playlists=tuple(playlists),
            path=series.path,
            tvdb_id=series.tvdb_id,
        )
    _save_locator_series(data_dir, loc, series)
    if platform == "dropout":
        loc, series = _find_locator(data_dir, platform, slug)
        assert isinstance(series, DropoutSeries)
        cache = _dropout_listing_cache(data_dir)
        try:
            _hydrate_dropout_listings_force(data_dir, series, environ, cache)
        except Exception as exc:
            logger.debug("listing hydration after refresh failed: %s", exc)
    from yt_dlp_emby.server.refresh_stamp import stamp_series_refresh

    stamp_series_refresh(data_dir, platform, slug, "listings")
    if patch_plan:
        _try_patch_plan(data_dir, platform, slug, environ)
    detail = get_series(data_dir, platform, slug)
    if source_error:
        for src in detail.get("sources") or []:
            if src.get("id") == str(source_id):
                src["error"] = source_error
    return detail


def _series_on_disk(
    data_dir: Path, platform: str, series_path: str, environ: Mapping[str, str]
) -> set[tuple[int, int]]:
    from yt_dlp_emby.config import resolve_settings
    from yt_dlp_emby.library import index_series_mkvs

    data, _ = _load_root_yaml(data_dir, platform)
    try:
        settings = resolve_settings(
            environ=environ,
            cwd=data_dir,
            manifest_library=str(data.get("library")) if data and data.get("library") else None,
            manifest_old_dir=str(data.get("old_dir")) if data and data.get("old_dir") else None,
            use_default_config=(data_dir / "config.toml").is_file(),
            auto_cookies=False,
        )
        folder = series_library_path(settings.library, series_path)
        return set(index_series_mkvs(folder))
    except (ConfigError, FFmpegNotFoundError, OSError, ValueError):
        return set()


def _dropout_listing_cache(data_dir: Path) -> dict[str, list[dict]]:
    from yt_dlp_emby.cache import dropout_cache_path, load_dropout_season_cache

    _, path = _load_root_yaml(data_dir, "dropout")
    return load_dropout_season_cache(dropout_cache_path(path))


def _dropout_cached_listings(
    data_dir: Path,
    series: DropoutSeries,
    source_id: int,
    season_obj,
    *,
    cache: dict[str, list[dict]] | None = None,
) -> list[Any] | None:
    from yt_dlp_emby.cache import dropout_listings_from_cache
    from yt_dlp_emby.dropout_manifest import season_page_url

    seasons = cache if cache is not None else _dropout_listing_cache(data_dir)
    page = season_page_url(series.sources[source_id], season_obj)
    return dropout_listings_from_cache(seasons.get(page))


def _write_listing_cache(data_dir: Path, cache: dict[str, list[dict]]) -> None:
    from yt_dlp_emby.cache import dropout_cache_path, save_dropout_season_cache

    _, path = _load_root_yaml(data_dir, "dropout")
    save_dropout_season_cache(dropout_cache_path(path), cache)


def _dropout_listings_complete(series: DropoutSeries, cache: dict[str, list[dict]]) -> bool:
    from yt_dlp_emby.cache import dropout_listings_from_cache
    from yt_dlp_emby.dropout_manifest import season_page_url

    for source in series.sources:
        for season_obj in source.seasons:
            if not season_obj.enabled:
                continue
            if dropout_listings_from_cache(cache.get(season_page_url(source, season_obj))) is None:
                return False
    return True


def _hydrate_dropout_listings_force(
    data_dir: Path,
    series: DropoutSeries,
    environ: Mapping[str, str],
    cache: dict[str, list[dict]],
) -> tuple[dict[str, list[dict]], str | None]:
    from yt_dlp_emby.auth import DropoutAuthError
    from yt_dlp_emby.cache import dropout_listings_to_cache
    from yt_dlp_emby.dropout_manifest import season_page_url

    cookie = str(_cookie_path_for_platform(data_dir, "dropout", environ))
    auth_error: str | None = None
    for source in series.sources:
        for season_obj in source.seasons:
            if not season_obj.enabled:
                continue
            page = season_page_url(source, season_obj)
            try:
                listings = extract_dropout_season(page, cookiefile=cookie)
            except DropoutAuthError as exc:
                return cache, str(exc)
            except Exception as exc:
                logger.debug("dropout listing fetch skipped for %s: %s", page, exc)
                continue
            cache[page] = dropout_listings_to_cache(listings)
            _write_listing_cache(data_dir, cache)
    return cache, auth_error


def _hydrate_dropout_listings(
    data_dir: Path,
    series: DropoutSeries,
    environ: Mapping[str, str],
    cache: dict[str, list[dict]],
) -> dict[str, list[dict]]:
    from yt_dlp_emby.auth import DropoutAuthError
    from yt_dlp_emby.cache import dropout_listings_from_cache, dropout_listings_to_cache
    from yt_dlp_emby.dropout_manifest import season_page_url

    cookie = str(_cookie_path_for_platform(data_dir, "dropout", environ))
    for source in series.sources:
        for season_obj in source.seasons:
            if not season_obj.enabled:
                continue
            page = season_page_url(source, season_obj)
            if dropout_listings_from_cache(cache.get(page)) is not None:
                continue
            try:
                listings = extract_dropout_season(page, cookiefile=cookie)
            except DropoutAuthError:
                return cache
            except Exception as exc:
                logger.debug("dropout listing fetch skipped for %s: %s", page, exc)
                continue
            cache[page] = dropout_listings_to_cache(listings)
            _write_listing_cache(data_dir, cache)
    return cache


def _store_dropout_listings(
    data_dir: Path,
    series: DropoutSeries,
    source_id: int,
    season_obj,
    listings: list[Any],
) -> None:
    from yt_dlp_emby.cache import dropout_listings_to_cache
    from yt_dlp_emby.dropout_manifest import season_page_url

    cached = _dropout_listing_cache(data_dir)
    page = season_page_url(series.sources[source_id], season_obj)
    cached[page] = dropout_listings_to_cache(listings)
    _write_listing_cache(data_dir, cached)


def _dropout_missing_count(
    data_dir: Path,
    series: DropoutSeries,
    environ: Mapping[str, str],
    *,
    cache: dict[str, list[dict]] | None = None,
) -> int | None:
    listings_cache = cache if cache is not None else _dropout_listing_cache(data_dir)
    on_disk = _series_on_disk(data_dir, "dropout", series.path, environ)
    missing = 0
    cached_any = False
    for source_id, source in enumerate(series.sources):
        for season_obj in source.seasons:
            if not season_obj.enabled:
                continue
            listings = _dropout_cached_listings(
                data_dir, series, source_id, season_obj, cache=listings_cache
            )
            if listings is None:
                continue
            cached_any = True
            for row in dropout_episode_rows(season_obj, listings, on_disk=on_disk):
                if row["status"] == "missing":
                    missing += 1
    if not cached_any:
        return None
    return missing


def series_missing_status(
    data_dir: Path,
    platform: str,
    slug: str,
    *,
    environ: Mapping[str, str],
    hydrate: bool = True,
) -> dict[str, Any]:
    _loc, series = _find_locator(data_dir, platform, slug)
    if platform != "dropout":
        from yt_dlp_emby.server.plan_series import plan_pending_for_slug

        return {
            "missing_count": plan_pending_for_slug(data_dir, platform, slug, environ=environ),
            "complete": True,
        }
    assert isinstance(series, DropoutSeries)
    cache = _dropout_listing_cache(data_dir)
    if hydrate:
        try:
            cache = _hydrate_dropout_listings(data_dir, series, environ, cache)
        except ConfigError:
            pass
    return {
        "missing_count": _dropout_missing_count(data_dir, series, environ, cache=cache),
        "complete": _dropout_listings_complete(series, cache),
    }


def series_poster_bytes(
    data_dir: Path,
    platform: str,
    slug: str,
    *,
    environ: Mapping[str, str],
) -> bytes | None:
    cache_dir = data_dir / "cache" / "posters"
    cached = cache_dir / f"{platform}_{slug}.jpg"
    stale: bytes | None = None
    if cached.is_file():
        try:
            ok = (time.time() - cached.stat().st_mtime) < POSTER_CACHE_TTL_SECONDS
            ok = ok and cached.stat().st_size > 0
        except OSError:
            ok = False
        if ok:
            return cached.read_bytes()
        # Stale entry: keep the bytes as a fallback if the refetch below fails.
        try:
            stale = cached.read_bytes() or None
        except OSError:
            stale = None
    detail = get_series(data_dir, platform, slug)
    tvdb_id = detail.get("tvdb_id")
    config_path = config_target_path(None, environ, data_dir)
    cfg = load_config_values(config_path) if config_path.is_file() else {}
    sonarr_url = (env_value(environ, "SONARR_URL") or cfg.get("sonarr_url") or "").strip()
    sonarr_key = (env_value(environ, "SONARR_API_KEY") or cfg.get("sonarr_api_key") or "").strip()
    if isinstance(tvdb_id, int) and sonarr_url and sonarr_key:
        from yt_dlp_emby.sonarr import fetch_sonarr_poster

        try:
            art = fetch_sonarr_poster(tvdb_id, base_url=sonarr_url, api_key=sonarr_key)
        except ConfigError:
            art = None
        if art:
            try:
                cache_dir.mkdir(parents=True, exist_ok=True)
                from yt_dlp_emby.images import write_image_from_bytes

                write_image_from_bytes(art, cached)
                return cached.read_bytes() if cached.is_file() else art
            except (OSError, ValueError):
                if art[:2] == b"\xff\xd8":
                    return art
                return stale
    series_path = str(detail.get("path") or "")
    if not series_path:
        return stale
    data, _ = _load_root_yaml(data_dir, platform)
    raw = (
        env_value(environ, "LIBRARY")
        or (str(data.get("library")) if data and data.get("library") else None)
        or cfg.get("library")
    )
    if not raw:
        return stale
    try:
        poster = series_library_path(Path(raw), series_path) / "poster.jpg"
        if poster.is_file():
            return poster.read_bytes()
    except (OSError, ValueError):
        return stale
    return stale


def _refresh_sonarr_cache(
    data_dir: Path,
    platform: str,
    tvdb_id: int,
    *,
    environ: Mapping[str, str],
) -> None:
    config_path = config_target_path(None, environ, data_dir)
    cfg = load_config_values(config_path) if config_path.is_file() else {}
    sonarr_url = (env_value(environ, "SONARR_URL") or cfg.get("sonarr_url") or "").strip()
    sonarr_key = (env_value(environ, "SONARR_API_KEY") or cfg.get("sonarr_api_key") or "").strip()
    if not sonarr_url or not sonarr_key:
        return
    from yt_dlp_emby.sonarr import fetch_episodes_cached, sonarr_cache_path

    _, path = _load_root_yaml(data_dir, platform)
    fetch_episodes_cached(
        tvdb_id,
        base_url=sonarr_url,
        api_key=sonarr_key,
        cache_path=sonarr_cache_path(path),
        force_refetch=True,
    )


def _normalize_refresh_parts(parts: list[str] | None) -> set[str]:
    allowed = {"listings", "disk", "sonarr"}
    if not parts:
        return set(allowed)
    out = {str(item).strip() for item in parts if str(item).strip()}
    if "all" in out or not out:
        return set(allowed)
    return {item for item in out if item in allowed}


def refresh_series_metadata(
    data_dir: Path,
    platform: str,
    slug: str,
    *,
    environ: Mapping[str, str],
    force: bool = True,
    parts: list[str] | None = None,
) -> str | None:
    """Refresh listings, disk plan rows, and/or Sonarr cache for one series."""
    from yt_dlp_emby.server.refresh_stamp import stamp_series_refresh

    wanted = _normalize_refresh_parts(parts)
    _loc, series = _find_locator(data_dir, platform, slug)
    listing_error: str | None = None
    if "listings" in wanted:
        if platform == "dropout":
            assert isinstance(series, DropoutSeries)
            cache = _dropout_listing_cache(data_dir)
            _cache, listing_error = _hydrate_dropout_listings_force(
                data_dir, series, environ, cache
            )
        else:
            assert isinstance(series, YoutubeSeries)
            cookie = str(_cookie_path_for_platform(data_dir, platform, environ))
            for pl in series.playlists:
                if pl.url:
                    try:
                        extract_playlist(pl.url, cookiefile=cookie)
                    except Exception as exc:
                        logger.debug("youtube listing refresh skipped for %s: %s", pl.url, exc)
                        continue
        stamp_series_refresh(data_dir, platform, slug, "listings")
    detail = get_series(data_dir, platform, slug)
    tvdb_id = detail.get("tvdb_id")
    if "sonarr" in wanted and isinstance(tvdb_id, int) and force:
        try:
            _refresh_sonarr_cache(data_dir, platform, tvdb_id, environ=environ)
            stamp_series_refresh(data_dir, platform, slug, "sonarr")
        except Exception as exc:
            logger.debug("sonarr refresh skipped for %s|%s: %s", platform, slug, exc)
    if "disk" in wanted or "listings" in wanted:
        _try_patch_plan(data_dir, platform, slug, environ)
    return listing_error


def refresh_series_batch(
    data_dir: Path,
    items: list[dict[str, str]],
    *,
    environ: Mapping[str, str],
    parts: list[str] | None = None,
) -> dict[str, Any]:
    results: list[dict[str, Any]] = []
    for item in items:
        platform = str(item.get("platform") or "")
        slug = str(item.get("slug") or "")
        if platform not in PLATFORMS or not slug:
            results.append({"platform": platform, "slug": slug, "error": "invalid item"})
            continue
        try:
            # No `with` block: Executor.__exit__ waits for workers, which would
            # defeat the timeout. On timeout the worker is detached (it still
            # finishes on its own socket timeouts); at most MAX_REFRESH_ITEMS
            # of them can pile up per batch.
            pool = ThreadPoolExecutor(max_workers=1)
            future = pool.submit(
                refresh_series_metadata,
                data_dir,
                platform,
                slug,
                environ=environ,
                force=True,
                parts=parts,
            )
            try:
                error = future.result(timeout=REFRESH_ITEM_TIMEOUT_SECONDS)
            except FuturesTimeoutError:
                pool.shutdown(wait=False, cancel_futures=True)
                error = (
                    f"refresh timed out after {REFRESH_ITEM_TIMEOUT_SECONDS:g}s "
                    f"for {platform}|{slug}"
                )
            else:
                pool.shutdown(wait=True)
            if error:
                error = sanitize_discovery_message(error, limit=500)
            results.append({"platform": platform, "slug": slug, "error": error})
        except KeyError:
            results.append({"platform": platform, "slug": slug, "error": "not found"})
        except Exception as exc:
            logger.debug("refresh failed for %s|%s: %s", platform, slug, exc)
            results.append(
                {
                    "platform": platform,
                    "slug": slug,
                    "error": sanitize_discovery_message(str(exc), limit=500),
                }
            )
    return {"ok": True, "results": results}


def series_disk_status(
    data_dir: Path, platform: str, slug: str, *, environ: Mapping[str, str]
) -> dict[str, Any]:
    detail = get_series(data_dir, platform, slug)
    on_disk = _series_on_disk(data_dir, platform, str(detail.get("path") or ""), environ)
    return {
        "on_disk": [{"season": season, "episode": episode} for season, episode in sorted(on_disk)]
    }


def list_series_episodes(
    data_dir: Path,
    platform: str,
    slug: str,
    source_id: int,
    season_id: int,
    *,
    environ: Mapping[str, str],
) -> dict[str, Any]:
    detail = get_series(data_dir, platform, slug)
    sources = detail.get("sources") or []
    if source_id < 0 or source_id >= len(sources):
        raise KeyError("source")
    source = sources[source_id]
    seasons = source.get("seasons") or []
    if season_id < 0 or season_id >= len(seasons):
        raise KeyError("season")
    season_json = seasons[season_id]
    on_disk = _series_on_disk(data_dir, platform, str(detail.get("path") or ""), environ)
    on_disk_payload = [
        {"season": season, "episode": episode} for season, episode in sorted(on_disk)
    ]
    if platform == "dropout":
        _, series = _find_locator(data_dir, platform, slug)
        assert isinstance(series, DropoutSeries)
        season_obj = series.sources[source_id].seasons[season_id]
        listings = _dropout_cached_listings(data_dir, series, source_id, season_obj)
        if listings is None:
            from yt_dlp_emby.dropout_manifest import season_page_url

            cookie = str(_cookie_path_for_platform(data_dir, platform, environ))
            url = season_page_url(series.sources[source_id], season_obj)
            listings = extract_dropout_season(url, cookiefile=cookie)
            _store_dropout_listings(data_dir, series, source_id, season_obj, listings)
        return {
            "episodes": dropout_episode_rows(season_obj, listings, on_disk=on_disk),
            "on_disk": on_disk_payload,
        }
    cookie = str(_cookie_path_for_platform(data_dir, platform, environ))
    url = str(source.get("url") or season_json.get("url") or "")
    playlist = extract_playlist(url, cookiefile=cookie)
    return {
        "episodes": youtube_episode_rows(season_json, playlist, on_disk=on_disk),
        "on_disk": on_disk_payload,
    }


def _validate_only_episodes(old: DropoutSeries, new: DropoutSeries) -> None:
    for oi, old_src in enumerate(old.sources):
        if oi >= len(new.sources):
            continue
        new_src = new.sources[oi]
        for si, old_se in enumerate(old_src.seasons):
            if si >= len(new_src.seasons):
                continue
            new_se = new_src.seasons[si]
            if old_se.only_episodes and not new_se.only_episodes:
                raise SeriesValidationError("only_episodes cannot be empty")


def _check_rename_conflicts(
    data_dir: Path,
    loc: SeriesLocator,
    old: DropoutSeries | YoutubeSeries,
    series: DropoutSeries | YoutubeSeries,
) -> None:
    if series.name.casefold() != old.name.casefold():
        others = _all_names(data_dir) - {old.name.casefold()}
        if series.name.casefold() in others:
            raise SeriesExistsError(f"A series named {series.name} already exists")
    new_path = series.path if isinstance(series, DropoutSeries) else (series.path or series.name)
    old_path = old.path if isinstance(old, DropoutSeries) else (old.path or old.name)
    if new_path.casefold() != old_path.casefold():
        others = _paths_for_platform(data_dir, loc.platform) - {old_path.casefold()}
        if new_path.casefold() in others:
            raise SeriesExistsError(
                f"A series with folder {new_path} already exists on {loc.platform}"
            )


def put_series(
    data_dir: Path,
    platform: str,
    slug: str,
    body: dict[str, Any],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    loc, old = _find_locator(data_dir, platform, slug)
    series: DropoutSeries | YoutubeSeries
    if platform == "dropout":
        series = _detail_to_dropout(body)
        assert isinstance(old, DropoutSeries)
        _validate_only_episodes(old, series)
    else:
        series = _detail_to_youtube(body)
    _check_rename_conflicts(data_dir, loc, old, series)
    _save_locator_series(data_dir, loc, series)
    _try_patch_plan(data_dir, platform, slug, environ)
    return get_series(data_dir, platform, slug)


def _dumps_yaml(data: Any) -> str:
    from io import StringIO

    from ruamel.yaml import YAML

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 4096
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    buf = StringIO()
    yaml_rt.dump(data, buf)
    return buf.getvalue()


def get_series_yaml(data_dir: Path, platform: str, slug: str) -> dict[str, Any]:
    loc, series = _find_locator(data_dir, platform, slug)
    item = (
        _dropout_series_to_yaml(series)
        if platform == "dropout"
        else _youtube_series_to_yaml(series)
    )
    return {"text": _dumps_yaml(item), "file": loc.file}


def put_series_yaml(
    data_dir: Path,
    platform: str,
    slug: str,
    text: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    loc, old = _find_locator(data_dir, platform, slug)
    try:
        parsed = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(format_yaml_error(exc)) from exc
    if parsed is None:
        raise ValueError("YAML is empty")
    if not isinstance(parsed, dict):
        raise ValueError("YAML must be a mapping")
    if "series" in parsed:
        raw_series = parsed.get("series")
        if not isinstance(raw_series, list) or len(raw_series) != 1:
            raise ValueError("YAML must contain exactly one series")
        raw: dict[str, Any] = {"series": raw_series}
    else:
        raw = {"series": [parsed]}
    try:
        items = list(_items_from_raw(platform, raw, Path(loc.file)))
    except ConfigError as exc:
        raise ValueError(str(exc)) from exc
    if len(items) != 1:
        raise ValueError("YAML must contain exactly one series")
    series = items[0]
    if platform == "dropout":
        assert isinstance(series, DropoutSeries)
        assert isinstance(old, DropoutSeries)
        _validate_only_episodes(old, series)
    _check_rename_conflicts(data_dir, loc, old, series)
    _save_locator_series(data_dir, loc, series)
    _try_patch_plan(data_dir, platform, slug, environ)
    entries = (
        _iter_dropout_entries(data_dir)
        if platform == "dropout"
        else _iter_youtube_entries(data_dir)
    )
    for found, _saved in entries:
        if found.file == loc.file and found.index == loc.index and found.inline == loc.inline:
            return get_series(data_dir, found.platform, found.slug)
    return get_series(data_dir, platform, slug)


def _cookie_jar_for_platform(data_dir: Path, kind: str, data: dict[str, Any]) -> dict[str, Any]:
    field = str(data.get("cookies") or "").strip()
    confined = confined_cookie_path(data_dir, field or None)
    from yt_dlp_emby.cookies import cookie_jar_path

    path = confined or cookie_jar_path(data_dir, kind)
    exists = path.is_file()
    return {
        "filename": path.name,
        "path": str(path),
        "exists": exists,
        "usable": cookies_file_usable(path) if exists else False,
    }


def platform_payload(data_dir: Path, kind: str, environ: Mapping[str, str]) -> dict[str, Any]:
    data, path = _load_root_yaml(data_dir, kind)
    paths = describe_manifest_paths(data if data else None, environ=environ, cwd=data_dir)
    return {
        "library": (data.get("library") or "") if data else "",
        "old_dir": (data.get("old_dir") or "") if data else "",
        "cookies": (data.get("cookies") or "") if data else "",
        "paths": paths,
        "cookie_jar": _cookie_jar_for_platform(data_dir, kind, data or {}),
    }


def put_platform(
    data_dir: Path,
    kind: str,
    values: Mapping[str, str | None],
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    env = environ if environ is not None else {}
    library = values.get("library")
    old_dir = values.get("old_dir")
    cookies = values.get("cookies")
    if library is not None and str(library).strip():
        validate_fs_dir_path(library, "library", data_dir=data_dir, environ=env)
    if old_dir is not None and str(old_dir).strip():
        validate_fs_dir_path(old_dir, "old_dir", data_dir=data_dir, environ=env)
    if cookies is not None and str(cookies).strip():
        validate_cookie_filename(cookies, data_dir=data_dir)
    data, path = _load_root_yaml(data_dir, kind)
    if not isinstance(data, dict):
        data = {}
    for key in ("library", "old_dir", "cookies"):
        val = values.get(key)
        if val is None or not str(val).strip():
            data.pop(key, None)
        else:
            data[key] = str(val).strip()
    _dump_yaml(path, data)
    return platform_payload(data_dir, kind, env)


def _dropout_manifest_parsed(data_dir: Path):
    from yt_dlp_emby.dropout_manifest import parse_dropout_manifest

    data, path = _load_root_yaml(data_dir, "dropout")
    return parse_dropout_manifest(data, path)


def _dropout_series_for_web_slug(data_dir: Path, slug: str) -> tuple[Any, DropoutSeries]:
    """Resolve a UI slug (file stem or slugify(name)) to the merged series."""
    _loc, located = _find_locator(data_dir, "dropout", slug)
    if not isinstance(located, DropoutSeries):
        raise KeyError(slug)
    manifest = _dropout_manifest_parsed(data_dir)
    series = next(
        (
            item
            for item in manifest.series
            if item.name.casefold() == located.name.casefold()
            and item.path.casefold() == located.path.casefold()
        ),
        located,
    )
    return manifest, series


def dropout_series_check(data_dir: Path, environ: Mapping[str, str], slug: str) -> dict[str, Any]:
    from yt_dlp_emby.config import resolve_settings
    from yt_dlp_emby.dropout_check import check_series_report

    manifest, series = _dropout_series_for_web_slug(data_dir, slug)
    settings = resolve_settings(
        environ=environ,
        cwd=data_dir,
        manifest_library=str(manifest.library) if manifest.library else None,
        manifest_old_dir=str(manifest.old_dir) if manifest.old_dir else None,
        manifest_staging=str(manifest.staging) if manifest.staging else None,
    )
    return check_series_report(manifest, settings, slugify(series.name), series=series)


def dropout_series_layout(data_dir: Path, environ: Mapping[str, str], slug: str) -> dict[str, Any]:
    from yt_dlp_emby.config import resolve_settings
    from yt_dlp_emby.dropout import layout_origin, resolve_emby_target, series_folder
    from yt_dlp_emby.dropout_check import _cached_listings
    from yt_dlp_emby.events import folder_label
    from yt_dlp_emby.library import emby_code, episode_stem, media_exists

    manifest, series = _dropout_series_for_web_slug(data_dir, slug)
    if not _cached_listings(manifest, series):
        raise ConfigError("List seasons first")
    settings = resolve_settings(
        environ=environ,
        cwd=data_dir,
        manifest_library=str(manifest.library) if manifest.library else None,
        manifest_old_dir=str(manifest.old_dir) if manifest.old_dir else None,
        manifest_staging=str(manifest.staging) if manifest.staging else None,
        dry_run=True,
        layout=True,
    )
    folders: dict[int, list[dict[str, Any]]] = {}
    titles: dict[int, str | None] = {}
    for _name, season, listing in _cached_listings(manifest, series):
        if season.title:
            titles[season.to_season if season.to_season is not None else season.dropout or 0] = (
                season.title
            )
        target = resolve_emby_target(listing, season)
        if target == "skip":
            continue
        if target is None:
            dest_key = -1
            row = {
                "code": None,
                "title": listing.title,
                "origin": None,
                "status": "unmapped",
            }
            folders.setdefault(dest_key, []).append(row)
            continue
        to_season, to_episode, title = target
        dest_dir = series_folder(settings, series) / folder_label(to_season)
        stem = episode_stem(series.name, to_season, to_episode, title)
        on_disk = media_exists(dest_dir, stem)
        row = {
            "code": emby_code(to_season, to_episode),
            "title": title,
            "origin": layout_origin(season, listing, to_season, to_episode),
            "status": "skip" if on_disk else "download",
        }
        folders.setdefault(to_season, []).append(row)
    ordered: list[dict[str, Any]] = []
    for dest in sorted(folders, key=lambda d: (d == -1, d == 0, d)):
        if dest == -1:
            ordered.append({"dest_season": None, "label": "unmapped", "episodes": folders[dest]})
            continue
        label = titles.get(dest) or folder_label(dest)
        ordered.append(
            {
                "dest_season": dest,
                "label": label,
                "folder": folder_label(dest),
                "episodes": sorted(folders[dest], key=lambda r: r.get("code") or ""),
            }
        )
    return {"folders": ordered}


def patch_platform_cookies_field(data_dir: Path, kind: str, filename: str) -> None:
    data, path = _load_root_yaml(data_dir, kind)
    if not isinstance(data, dict):
        data = {}
    if data.get("cookies") == filename:
        return
    data["cookies"] = filename
    _dump_yaml(path, data)
