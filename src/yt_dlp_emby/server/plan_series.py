"""Patch plan.json for a single series without a full-platform dry-run."""

from __future__ import annotations

import copy
import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Any, Mapping

from yt_dlp_emby.config import ConfigError, FFmpegNotFoundError, resolve_settings
from yt_dlp_emby.events import capture_events, merge_plan_slug, plan_from_events
from yt_dlp_emby.series_ids import slugify
from yt_dlp_emby.server.refresh_stamp import stamp_series_refresh
from yt_dlp_emby.server.runner import PLAN_NAME, load_plan_file

logger = logging.getLogger("yt_dlp_emby.server")

PLAN_ACTIONS = {"download", "replace"}
_EPISODE_CODE = re.compile(r"S(\d{2})E(\d+)", re.I)


def plan_path(data_dir: Path) -> Path:
    return data_dir / PLAN_NAME


def plan_item_slot(item: Mapping[str, Any]) -> tuple[int, int] | None:
    code = item.get("code")
    if not code:
        ident = item.get("id")
        if isinstance(ident, str) and ident.count("|") >= 2:
            code = ident.rsplit("|", 1)[-1]
    if not isinstance(code, str):
        return None
    match = _EPISODE_CODE.search(code)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def load_live_plan(
    data_dir: Path, environ: Mapping[str, str] | None = None
) -> dict[str, Any] | None:
    """plan.json with download rows dropped when those files already exist.

    Shows and Downloads both treat `index_series_mkvs` as the on-disk truth.
    The stored plan is a dry-run snapshot and can lag behind the library.
    """
    plan = load_plan_file(data_dir)
    if plan is None:
        return None
    return reconcile_plan_with_library(data_dir, plan, environ or {})


def reconcile_plan_with_library(
    data_dir: Path,
    plan: dict[str, Any],
    environ: Mapping[str, str],
) -> dict[str, Any]:
    if plan.get("force"):
        return plan
    sources = plan.get("sources")
    if not isinstance(sources, dict):
        return plan
    out = copy.deepcopy(plan)
    disk_cache: dict[tuple[str, str], set[tuple[int, int]] | None] = {}
    changed = False
    for platform, block in (out.get("sources") or {}).items():
        if not isinstance(block, dict) or platform not in {"dropout", "youtube"}:
            continue
        items = [row for row in block.get("items") or [] if isinstance(row, dict)]
        kept: list[dict[str, Any]] = []
        for item in items:
            if item.get("action") != "download":
                kept.append(item)
                continue
            slot = plan_item_slot(item)
            slug = item.get("slug")
            if slot is None or not isinstance(slug, str):
                kept.append(item)
                continue
            on_disk = _on_disk_for_plan_slug(data_dir, platform, slug, environ, cache=disk_cache)
            if on_disk is not None and slot in on_disk:
                changed = True
                continue
            kept.append(item)
        if len(kept) != len(items):
            block["items"] = kept
            _recount_season_downloads(block)
            changed = True
    return out if changed else plan


def _on_disk_for_plan_slug(
    data_dir: Path,
    platform: str,
    slug: str,
    environ: Mapping[str, str],
    *,
    cache: dict[tuple[str, str], set[tuple[int, int]] | None],
) -> set[tuple[int, int]] | None:
    key = (platform, slug)
    if key in cache:
        return cache[key]
    from yt_dlp_emby.server.series import (
        AmbiguousSlugError,
        _series_on_disk,
        locate_series,
        series_folder_rel,
    )

    try:
        loc, series = locate_series(data_dir, platform, slug)
    except (KeyError, AmbiguousSlugError):
        cache[key] = None
        return None
    on_disk = _series_on_disk(data_dir, platform, series_folder_rel(series), environ)
    cache[key] = on_disk
    cache[(platform, loc.slug)] = on_disk
    return on_disk


def _recount_season_downloads(block: dict[str, Any]) -> None:
    counts: Counter[tuple[str, int]] = Counter()
    for item in block.get("items") or []:
        if not isinstance(item, dict) or item.get("action") != "download":
            continue
        slug = item.get("slug")
        dest = item.get("dest_season")
        if dest is None:
            slot = plan_item_slot(item)
            dest = slot[0] if slot else None
        if not isinstance(slug, str) or dest is None:
            continue
        counts[(slug, int(dest))] += 1
    for season in block.get("seasons") or []:
        if not isinstance(season, dict) or "download" not in season:
            continue
        slug = season.get("slug")
        dest = season.get("dest_season")
        if not isinstance(slug, str) or dest is None:
            continue
        season["download"] = counts.get((slug, int(dest)), 0)


def plan_pending_for_slug(
    data_dir: Path,
    platform: str,
    slug: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> int | None:
    plan = load_live_plan(data_dir, environ)
    if plan is None:
        return None
    block = (plan.get("sources") or {}).get(platform)
    if not isinstance(block, dict):
        return None
    slugs = {slug}
    try:
        from yt_dlp_emby.server.series import AmbiguousSlugError, locate_series

        loc, series = locate_series(data_dir, platform, slug)
        slugs.update({loc.slug, slugify(series.name)})
    except (KeyError, AmbiguousSlugError):
        pass
    count = 0
    found = False
    for row in block.get("items") or []:
        if not isinstance(row, dict) or row.get("slug") not in slugs:
            continue
        found = True
        if row.get("action") in PLAN_ACTIONS:
            count += 1
    if not found:
        for row in block.get("seasons") or []:
            if isinstance(row, dict) and row.get("slug") in slugs:
                found = True
                break
    return count if found else None


def _web_settings(
    data_dir: Path,
    platform: str,
    environ: Mapping[str, str],
    *,
    force_refetch: bool = False,
):
    from yt_dlp_emby.server.series import _load_root_yaml

    data, _ = _load_root_yaml(data_dir, platform)
    return resolve_settings(
        environ=environ,
        cwd=data_dir,
        manifest_library=str(data.get("library")) if data and data.get("library") else None,
        manifest_old_dir=str(data.get("old_dir")) if data and data.get("old_dir") else None,
        manifest_staging=str(data.get("staging")) if data and data.get("staging") else None,
        use_default_config=(data_dir / "config.toml").is_file(),
        dry_run=True,
        quiet=True,
        force_refetch=force_refetch,
    )


def patch_series_plan(
    data_dir: Path,
    platform: str,
    slug: str,
    *,
    environ: Mapping[str, str],
    force_refetch: bool = False,
) -> None:
    from yt_dlp_emby.server.series import _find_locator

    _loc, series = _find_locator(data_dir, platform, slug)
    aliases = {slugify(series.name), slug}
    try:
        settings = _web_settings(data_dir, platform, environ, force_refetch=force_refetch)
    except (ConfigError, FFmpegNotFoundError):
        return
    error: str | None = None
    with capture_events() as events:
        try:
            if platform == "dropout":
                from yt_dlp_emby.dropout import run_dropout
                from yt_dlp_emby.dropout_manifest import filter_dropout_manifest
                from yt_dlp_emby.server.series import _dropout_manifest_parsed

                manifest = filter_dropout_manifest(
                    _dropout_manifest_parsed(data_dir),
                    series_names=[series.name],
                )
                run_dropout(manifest, settings)
            else:
                from yt_dlp_emby.pipeline import run_youtube_manifest
                from yt_dlp_emby.server.series import _load_root_yaml
                from yt_dlp_emby.youtube_manifest import (
                    filter_youtube_manifest,
                    parse_youtube_manifest,
                )

                data, path = _load_root_yaml(data_dir, "youtube")
                yt_manifest = filter_youtube_manifest(
                    parse_youtube_manifest(data, path),
                    series_names=[series.name],
                )
                run_youtube_manifest(yt_manifest, settings)
        except Exception as exc:
            error = str(exc)
    payload = plan_from_events(events, platform=platform)
    if error:
        payload["ok"] = False
        payload["error"] = error
    merge_plan_slug(
        plan_path(data_dir),
        platform,
        slug,
        payload,
        aliases=aliases,
    )
    stamp_series_refresh(data_dir, platform, slug, "disk")


def slugs_in_plan_source(plan: dict[str, Any] | None, platform: str) -> set[str]:
    if not plan:
        return set()
    block = (plan.get("sources") or {}).get(platform)
    if not isinstance(block, dict):
        return set()
    out: set[str] = set()
    for row in list(block.get("seasons") or []) + list(block.get("items") or []):
        if isinstance(row, dict) and row.get("slug"):
            out.add(str(row["slug"]))
    return out


def slugs_from_only_ids(only_path: Path | None, platform: str) -> set[str] | None:
    if only_path is None or not only_path.is_file():
        return None
    try:
        data = json.loads(only_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    ids = data.get("ids")
    if not isinstance(ids, list):
        return None
    prefix = f"{platform}|"
    slugs = set()
    for item in ids:
        text = str(item)
        if not text.startswith(prefix):
            continue
        parts = text.split("|")
        if len(parts) >= 2:
            slugs.add(parts[1])
    return slugs


def sync_plan_after_run(
    data_dir: Path,
    platform: str,
    *,
    environ: Mapping[str, str],
    dry_run: bool,
    only_path: Path | None,
) -> None:
    plan = load_plan_file(data_dir)
    slugs = slugs_from_only_ids(only_path, platform)
    if slugs is None:
        slugs = slugs_in_plan_source(plan, platform)
    if dry_run:
        for slug in slugs:
            stamp_series_refresh(data_dir, platform, slug, "disk", "listings")
        return
    for slug in slugs:
        try:
            patch_series_plan(data_dir, platform, slug, environ=environ)
        except Exception as exc:
            logger.debug("plan patch skipped for %s|%s: %s", platform, slug, exc)
            continue
