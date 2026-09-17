"""Structured series API (no merge by path)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

import yaml

from yt_dlp_emby.config import (
    ConfigError,
    describe_manifest_paths,
    env_value,
    load_config_values,
    config_target_path,
)
from yt_dlp_emby.ffmpeg import FFmpegNotFoundError
from yt_dlp_emby.dropout_manifest import (
    DropoutRemap,
    DropoutSeason,
    DropoutSeries,
    DropoutSource,
    parse_dropout_series_file,
)
from yt_dlp_emby.series_ids import slugify
from yt_dlp_emby.server.manifests import ALLOWED, _confined_import_path, _manifest_path
from yt_dlp_emby.cookies import (
    DEFAULT_COOKIE_FILES,
    confined_cookie_path,
    cookies_file_usable,
    inspect_cookie_jars,
)
from yt_dlp_emby.extract import extract_dropout_season, extract_playlist
from yt_dlp_emby.server.series_discover import (
    ChannelDiscoverError,
    discover_dropout_source,
    discover_youtube_sources,
    dropout_episode_rows,
    merge_dropout_seasons,
    youtube_episode_rows,
)
from yt_dlp_emby.youtube_manifest import (
    YoutubePlaylist,
    YoutubeSeries,
    parse_youtube_series_file,
)

PLATFORMS = frozenset({"youtube", "dropout"})


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
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}, path
    return data, path


def _imports_from_data(data: dict[str, Any]) -> tuple[str, ...]:
    raw = data.get("imports")
    if not isinstance(raw, list):
        return ()
    return tuple(item.strip() for item in raw if isinstance(item, str) and item.strip())


def _iter_dropout_entries(data_dir: Path) -> list[tuple[SeriesLocator, DropoutSeries]]:
    out: list[tuple[SeriesLocator, DropoutSeries]] = []
    data, root_path = _load_root_yaml(data_dir, "dropout")
    if data:
        inline: tuple[DropoutSeries, ...] = ()
        try:
            inline = parse_dropout_series_file({"series": data.get("series") or []}, root_path)
        except ConfigError:
            inline = ()
        for i, series in enumerate(inline):
            slug = slugify(series.name)
            out.append(
                (
                    SeriesLocator("dropout", slug, "dropout.yaml", True, i),
                    series,
                )
            )
        for rel in _imports_from_data(data):
                confined = _confined_import_path(data_dir, rel)
                if confined is None or not confined.is_file():
                    continue
                try:
                    items = parse_dropout_series_file(
                        yaml.safe_load(confined.read_text(encoding="utf-8")),
                        confined,
                    )
                except ConfigError:
                    continue
                stem = confined.stem
                for j, series in enumerate(items):
                    slug = _slug_for_file(len(items), stem, series.name)
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
    return out


def _iter_youtube_entries(data_dir: Path) -> list[tuple[SeriesLocator, YoutubeSeries]]:
    out: list[tuple[SeriesLocator, YoutubeSeries]] = []
    data, root_path = _load_root_yaml(data_dir, "youtube")
    if data:
        inline: tuple[YoutubeSeries, ...] = ()
        try:
            inline = parse_youtube_series_file({"series": data.get("series") or []}, root_path)
        except ConfigError:
            inline = ()
        for i, series in enumerate(inline):
            slug = slugify(series.name)
            out.append(
                (
                    SeriesLocator("youtube", slug, "youtube.yaml", True, i),
                    series,
                )
            )
        for rel in _imports_from_data(data):
                confined = _confined_import_path(data_dir, rel)
                if confined is None or not confined.is_file():
                    continue
                try:
                    items = parse_youtube_series_file(
                        yaml.safe_load(confined.read_text(encoding="utf-8")),
                        confined,
                    )
                except ConfigError:
                    continue
                stem = confined.stem
                for j, series in enumerate(items):
                    slug = _slug_for_file(len(items), stem, series.name)
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
    return out


def _find_locator(data_dir: Path, platform: str, slug: str) -> tuple[SeriesLocator, DropoutSeries | YoutubeSeries]:
    if platform not in PLATFORMS:
        raise KeyError(slug)
    slug_cf = slug.casefold()
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
            raise ValueError(f"ambiguous slug {slug}")
        return imported[0]
    if len(matches) > 1:
        raise ValueError(f"ambiguous slug {slug}")
    return matches[0]


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
            to_season = season.to_season if season.to_season is not None else season.dropout
            label, sublabel = _season_label(to_season, season.dropout, season.title)
            seasons.append(
                {
                    "id": str(seid),
                    "dropout": season.dropout,
                    "url": season.url,
                    "to_season": to_season,
                    "enabled": season.enabled,
                    "title": season.title,
                    "only_episodes": list(season.only_episodes)
                    if season.only_episodes
                    else None,
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
        block["episodes"] = sorted(
            e for ss, e in series.tvdb_skip if ss == block["season"]
        )
    enabled_seasons = sum(
        1 for src in series.sources for se in src.seasons if se.enabled
    )
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
    }


def _youtube_series_to_detail(
    loc: SeriesLocator,
    series: YoutubeSeries,
    *,
    errors: Mapping[int, str] | None = None,
) -> dict[str, Any]:
    sources: list[dict[str, Any]] = []
    for sid, pl in enumerate(series.playlists):
        to_season = pl.season or (sid + 1)
        label, sublabel = _season_label(to_season, None, pl.title)
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
    }


def list_series(
    data_dir: Path, environ: Mapping[str, str] | None = None
) -> dict[str, Any]:
    env = environ or {}
    items: list[dict[str, Any]] = []
    dropout_cache = _dropout_listing_cache(data_dir)
    for loc, series in _iter_dropout_entries(data_dir):
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
                "missing_count": _dropout_missing_count(
                    data_dir, series, env, cache=dropout_cache
                ),
                "listings_complete": _dropout_listings_complete(
                    series, dropout_cache
                ),
            }
        )
    for loc, series in _iter_youtube_entries(data_dir):
        detail = _youtube_series_to_detail(loc, series)
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
                "missing_count": None,
                "listings_complete": False,
            }
        )
    items.sort(key=lambda row: row["name"].casefold())
    return {"series": items}


def get_series(data_dir: Path, platform: str, slug: str) -> dict[str, Any]:
    loc, series = _find_locator(data_dir, platform, slug)
    if platform == "dropout":
        assert isinstance(series, DropoutSeries)
        return _dropout_series_to_detail(loc, series)
    assert isinstance(series, YoutubeSeries)
    return _youtube_series_to_detail(loc, series)


def _all_names(data_dir: Path) -> set[str]:
    names: set[str] = set()
    for _, s in _iter_dropout_entries(data_dir):
        names.add(s.name.casefold())
    for _, s in _iter_youtube_entries(data_dir):
        names.add(s.name.casefold())
    return names


def _paths_for_platform(data_dir: Path, platform: str) -> set[str]:
    paths: set[str] = set()
    if platform == "dropout":
        for _, s in _iter_dropout_entries(data_dir):
            if s.path:
                paths.add(s.path.casefold())
    else:
        for _, s in _iter_youtube_entries(data_dir):
            p = s.path or s.name
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
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_child_dropout(path: Path, series: DropoutSeries) -> None:
    payload = {"series": [_dropout_series_to_yaml(series)]}
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _write_child_youtube(path: Path, series: YoutubeSeries) -> None:
    payload = {"series": [_youtube_series_to_yaml(series)]}
    text = yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


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
        raise ValueError("unknown platform")
    name = name.strip()
    path = path.strip()
    if not name or not path:
        raise ValueError("name and path are required")
    slug = slugify(name)
    if not slug:
        raise ValueError("invalid title for slug")
    if name.casefold() in _all_names(data_dir):
        raise ValueError(f"A series named {name} already exists")
    if path.casefold() in _paths_for_platform(data_dir, platform):
        raise ValueError(f"A series with folder {path} already exists on {platform}")
    shows = resolve_shows_dir(data_dir, environ)
    child = shows / f"{slug}.yaml"
    if child.exists():
        raise ValueError("slug already exists")
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
        path=str(body["path"]),
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
    return YoutubeSeries(
        name=str(body["name"]),
        playlists=tuple(playlists),
        path=str(body.get("path") or body["name"]),
        tvdb_id=int(tvdb) if tvdb is not None else None,
    )


def _dump_yaml(path: Path, data: dict[str, Any]) -> None:
    text = yaml.safe_dump(data, sort_keys=False, allow_unicode=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def _cookie_path_for_platform(
    data_dir: Path, platform: str, environ: Mapping[str, str]
) -> Path:
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


def _items_from_raw(
    platform: str, raw: dict[str, Any], path: Path
) -> list[DropoutSeries] | list[YoutubeSeries]:
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
        yaml_items = [_dropout_series_to_yaml(s) for s in items]  # type: ignore[arg-type]
    else:
        yaml_items = [_youtube_series_to_yaml(s) for s in items]  # type: ignore[arg-type]
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
        seasons_raw = discover_dropout_source(
            url, cookiefile=cookie, fetch_html=fetch_html
        )
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
            source_error = exc.message
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
    return detail


def delete_series_source(
    data_dir: Path, platform: str, slug: str, source_id: int
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
        seasons_raw = discover_dropout_source(
            source.url, cookiefile=cookie, fetch_html=fetch_html
        )
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
            source_error = exc.message
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
        return set(index_series_mkvs(settings.library / series_path))
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


def _dropout_listings_complete(
    series: DropoutSeries, cache: dict[str, list[dict]]
) -> bool:
    from yt_dlp_emby.cache import dropout_listings_from_cache
    from yt_dlp_emby.dropout_manifest import season_page_url

    for source in series.sources:
        for season_obj in source.seasons:
            if not season_obj.enabled:
                continue
            if dropout_listings_from_cache(cache.get(season_page_url(source, season_obj))) is None:
                return False
    return True


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
            except Exception:
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
        return {"missing_count": None, "complete": False}
    assert isinstance(series, DropoutSeries)
    cache = _dropout_listing_cache(data_dir)
    if hydrate:
        try:
            cache = _hydrate_dropout_listings(data_dir, series, environ, cache)
        except ConfigError:
            pass
    return {
        "missing_count": _dropout_missing_count(
            data_dir, series, environ, cache=cache
        ),
        "complete": _dropout_listings_complete(series, cache),
    }


def series_disk_status(
    data_dir: Path, platform: str, slug: str, *, environ: Mapping[str, str]
) -> dict[str, Any]:
    detail = get_series(data_dir, platform, slug)
    on_disk = _series_on_disk(data_dir, platform, str(detail.get("path") or ""), environ)
    return {
        "on_disk": [
            {"season": season, "episode": episode} for season, episode in sorted(on_disk)
        ]
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
                raise ValueError("only_episodes cannot be empty")


def _check_rename_conflicts(
    data_dir: Path,
    loc: SeriesLocator,
    old: DropoutSeries | YoutubeSeries,
    series: DropoutSeries | YoutubeSeries,
) -> None:
    if series.name.casefold() != old.name.casefold():
        others = _all_names(data_dir) - {old.name.casefold()}
        if series.name.casefold() in others:
            raise ValueError(f"A series named {series.name} already exists")
    new_path = series.path if isinstance(series, DropoutSeries) else (series.path or series.name)
    old_path = old.path if isinstance(old, DropoutSeries) else (old.path or old.name)
    if new_path.casefold() != old_path.casefold():
        others = _paths_for_platform(data_dir, loc.platform) - {old_path.casefold()}
        if new_path.casefold() in others:
            raise ValueError(
                f"A series with folder {new_path} already exists on {loc.platform}"
            )


def put_series(data_dir: Path, platform: str, slug: str, body: dict[str, Any]) -> dict[str, Any]:
    loc, old = _find_locator(data_dir, platform, slug)
    if platform == "dropout":
        series = _detail_to_dropout(body)
        assert isinstance(old, DropoutSeries)
        _validate_only_episodes(old, series)
    else:
        series = _detail_to_youtube(body)
    _check_rename_conflicts(data_dir, loc, old, series)
    _save_locator_series(data_dir, loc, series)
    return get_series(data_dir, platform, slug)


def _cookie_jar_for_platform(
    data_dir: Path, kind: str, data: dict[str, Any]
) -> dict[str, Any]:
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


def platform_payload(
    data_dir: Path, kind: str, environ: Mapping[str, str]
) -> dict[str, Any]:
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
    env = environ if environ is not None else {}
    return platform_payload(data_dir, kind, env)


def _dropout_manifest_parsed(data_dir: Path):
    from yt_dlp_emby.dropout_manifest import parse_dropout_manifest

    data, path = _load_root_yaml(data_dir, "dropout")
    return parse_dropout_manifest(data, path)


def _dropout_series_for_web_slug(
    data_dir: Path, slug: str
) -> tuple[Any, DropoutSeries]:
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


def dropout_series_check(
    data_dir: Path, environ: Mapping[str, str], slug: str
) -> dict[str, Any]:
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
    return check_series_report(
        manifest, settings, slugify(series.name), series=series
    )


def dropout_series_layout(
    data_dir: Path, environ: Mapping[str, str], slug: str
) -> dict[str, Any]:
    from yt_dlp_emby.config import resolve_settings
    from yt_dlp_emby.dropout import layout_origin, resolve_emby_target
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
        dest_dir = settings.library / series.path / folder_label(to_season)
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

