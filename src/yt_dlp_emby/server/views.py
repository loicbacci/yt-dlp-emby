"""Cached web projections. These reads never contact providers or scan media."""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

from yt_dlp_emby.config import ConfigError, env_value
from yt_dlp_emby.dropout import resolve_emby_target
from yt_dlp_emby.dropout_manifest import DropoutSeries
from yt_dlp_emby.extract import DropoutListing, EpisodeInfo, PlaylistInfo
from yt_dlp_emby.server.job_store import JobStore
from yt_dlp_emby.server.series import get_series, list_series, locate_series
from yt_dlp_emby.server.series_discover import dropout_episode_rows, youtube_episode_rows
from yt_dlp_emby.server.services import ProviderListing, plan_variant
from yt_dlp_emby.youtube_manifest import YoutubeSeries

CACHE_TTL = timedelta(hours=24)


def source_signature(series: DropoutSeries | YoutubeSeries) -> str:
    """Hash provider identity and disk location independently of mapping edits."""
    sources: list[dict[str, Any]]
    if isinstance(series, DropoutSeries):
        sources = [
            {
                "url": source.url,
                "seasons": [
                    (season.dropout, season.url, season.enabled) for season in source.seasons
                ],
            }
            for source in series.sources
        ]
    else:
        sources = [{"url": source.url, "enabled": source.enabled} for source in series.playlists]
    raw = {"name": series.name, "path": series.path, "sources": sources}
    return hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest()


def configuration_context_signature(
    data_dir: Path, environ: Mapping[str, str], platform: str
) -> str:
    """Detect path/settings edits while permitting sibling and mapping saves."""
    from yt_dlp_emby.server.series import _load_root_yaml
    from yt_dlp_emby.server.services import load_config_snapshot

    config = load_config_snapshot(data_dir, environ)
    root, _path = _load_root_yaml(data_dir, platform)
    raw = {
        "settings_path": config.path,
        "settings": config.revision,
        "root": {key: value for key, value in root.items() if key != "series"},
        "effective_environment": {
            key: environ.get(key) or env_value(environ, key)
            for key in (
                "LIBRARY",
                "OLD_DIR",
                "STAGING",
                "CONFIG",
                "FFMPEG",
                "COOKIES",
                "YOUTUBE_COOKIES",
                "DROPOUT_COOKIES",
                "SONARR_URL",
                "SONARR_API_KEY",
                "SHOWS_DIR",
            )
        },
    }
    return hashlib.sha256(json.dumps(raw, sort_keys=True, default=str).encode()).hexdigest()


def _error_text(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return str(
            value.get("message") or value.get("error") or value.get("code") or "Refresh failed"
        )
    return str(value)


def cache_is_stale(record: Mapping[str, Any] | None, *, now: datetime | None = None) -> bool:
    """A missing, failed, or older-than-TTL cache is eligible for revalidation."""
    if not record or record.get("freshness") != "ready":
        return True
    view = _view(record)
    times = (view or {}).get("cache_times")
    values = (
        list(times.values())
        if isinstance(times, Mapping) and times
        else [record.get("last_success_at")]
    )
    if not values:
        return True
    current = now or datetime.now(timezone.utc)
    for value in values:
        if not isinstance(value, str):
            return True
        try:
            fetched = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
        except ValueError:
            return True
        if current - fetched >= CACHE_TTL:
            return True
    return False


def cache_part_is_stale(
    record: Mapping[str, Any] | None, part: str, *, now: datetime | None = None
) -> bool:
    view = _view(record)
    times = (view or {}).get("cache_times")
    value = times.get(part) if isinstance(times, Mapping) else None
    if not isinstance(value, str):
        return True
    try:
        fetched = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if fetched.tzinfo is None:
            fetched = fetched.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    return (now or datetime.now(timezone.utc)) - fetched >= CACHE_TTL


def _view(record: Mapping[str, Any] | None) -> dict[str, Any] | None:
    if not record:
        return None
    inputs = record.get("inputs")
    if not isinstance(inputs, Mapping):
        return None
    value = inputs.get("view", inputs)
    return dict(value) if isinstance(value, Mapping) else None


def _current(
    data_dir: Path,
    environ: Mapping[str, str],
    platform: str,
    slug: str,
    record: Mapping[str, Any] | None,
) -> bool:
    view = _view(record)
    if not view or not record or record.get("freshness") != "ready" or view.get("stale"):
        return False
    from yt_dlp_emby.server.services import current_configuration_revision

    try:
        return view.get("config_revision") == current_configuration_revision(
            data_dir, environ, platform, slug
        )
    except (OSError, ValueError, KeyError, ConfigError):
        return False


def _cached_config_matches(
    data_dir: Path,
    environ: Mapping[str, str],
    platform: str,
    slug: str,
    record: Mapping[str, Any] | None,
) -> bool:
    view = _view(record)
    if not view or not record or not record.get("last_success_at"):
        return False
    try:
        _loc, series = locate_series(data_dir, platform, slug)
        from yt_dlp_emby.server.services import current_configuration_revision

        return (
            view.get("config_revision")
            == current_configuration_revision(data_dir, environ, platform, slug)
            and view.get("source_signature") == source_signature(series)
            and view.get("context_signature")
            == configuration_context_signature(data_dir, environ, platform)
        )
    except (OSError, ValueError, KeyError, ConfigError):
        return False


def disk_view(
    data_dir: Path, environ: Mapping[str, str], store: JobStore, platform: str, slug: str
) -> dict[str, Any]:
    get_series(data_dir, platform, slug)  # Keep existing 404/ambiguity behavior.
    record = store.get_view(platform, slug)
    view = _view(record)
    disk = (view or {}).get("disk") or {}
    ready = (
        _cached_config_matches(data_dir, environ, platform, slug, record)
        and disk.get("status") == "ready"
    )
    episodes = disk.get("episodes") or []
    return {
        "status": "ready" if ready else "unavailable",
        "state": "ready" if ready else "unavailable",
        "on_disk": [{"season": int(row[0]), "episode": int(row[1])} for row in episodes],
        "series_exists": disk.get("series_exists") if ready else None,
        "stale": not ready or cache_is_stale(record),
        "error": _error_text((record or {}).get("error"))
        or (disk.get("error") if not ready else None)
        or ("Refresh required" if not ready else None),
        "last_attempt_at": (record or {}).get("last_attempt_at"),
        "last_success_at": (record or {}).get("last_success_at"),
        "cache_stale": cache_is_stale(record),
    }


def missing_view(
    data_dir: Path, environ: Mapping[str, str], store: JobStore, platform: str, slug: str
) -> dict[str, Any]:
    disk = disk_view(data_dir, environ, store, platform, slug)
    record = store.get_view(platform, slug)
    view = _view(record)
    count = None
    if disk["status"] == "ready" and view is not None and view.get("listings_complete", True):
        plan = plan_variant(view, create=True)
        count = sum(
            row.get("action") in {"download", "replace"}
            for block in plan["sources"].values()
            for row in block.get("items", [])
        )
    return {
        "missing_count": count,
        "complete": count is not None,
        "status": disk["status"],
        "error": disk["error"],
        "stale": disk["stale"],
        "last_attempt_at": disk["last_attempt_at"],
        "last_success_at": disk["last_success_at"],
        "cache_stale": disk["cache_stale"],
    }


def series_detail(
    data_dir: Path, environ: Mapping[str, str], store: JobStore, platform: str, slug: str
) -> dict[str, Any]:
    detail = get_series(data_dir, platform, slug)
    record = store.get_view(platform, slug)
    detail.update(missing_view(data_dir, environ, store, platform, slug))
    detail["listings_complete"] = detail["complete"]
    view = _view(record)
    from yt_dlp_emby.server.services import current_configuration_revision

    detail["cached_config_revision"] = (view or {}).get("config_revision")
    try:
        detail["config_revision"] = current_configuration_revision(
            data_dir, environ, platform, slug
        )
    except (OSError, ValueError, KeyError, ConfigError):
        detail["config_revision"] = None
    cache_times = (view or {}).get("cache_times") or {}
    detail["refreshed"] = {
        "listings": cache_times.get("listings") or (record or {}).get("last_success_at"),
        "disk": cache_times.get("disk") or (record or {}).get("last_success_at"),
        "sonarr": cache_times.get("sonarr"),
    }
    detail["sonarr_error"] = (view or {}).get("sonarr_error")
    detail["cache_states"] = {
        part: {
            "stale": cache_part_is_stale(record, part),
            "error": (view or {}).get(f"{part}_error"),
        }
        for part in ("listings", "disk", "sonarr")
    }
    return detail


def series_list(data_dir: Path, environ: Mapping[str, str], store: JobStore) -> dict[str, Any]:
    hydrate_catalog_cache(data_dir, store)
    payload = list_series(data_dir, environ=environ)
    for row in payload["series"]:
        state = missing_view(data_dir, environ, store, row["platform"], row["slug"])
        record = store.get_view(row["platform"], row["slug"])
        view = _view(record) or {}
        row.update(state)
        row["listings_complete"] = state["complete"]
        cache_times = view.get("cache_times") or {}
        row["refreshed"] = {
            "listings": cache_times.get("listings") or state["last_success_at"],
            "disk": cache_times.get("disk") or state["last_success_at"],
            "sonarr": cache_times.get("sonarr"),
        }
        row["sonarr_error"] = view.get("sonarr_error")
        row["cache_states"] = {
            part: {
                "stale": cache_part_is_stale(record, part),
                "error": view.get(f"{part}_error"),
            }
            for part in ("listings", "disk", "sonarr")
        }
    return payload


def episodes_view(
    data_dir: Path,
    environ: Mapping[str, str],
    store: JobStore,
    platform: str,
    slug: str,
    source_id: int,
    season_id: int,
) -> dict[str, Any]:
    detail = get_series(data_dir, platform, slug)
    sources = detail.get("sources") or []
    if not 0 <= source_id < len(sources) or not 0 <= season_id < len(
        sources[source_id].get("seasons") or []
    ):
        raise KeyError("source or season")
    record = store.get_view(platform, slug)
    view = _view(record)
    disk = disk_view(data_dir, environ, store, platform, slug)
    listings = [
        row
        for row in (view or {}).get("provider_listings", [])
        if row.get("source_index") == source_id
        and row.get("season_index") == season_id
        and not row.get("empty_listing")
    ]
    on_disk = {(int(row["season"]), int(row["episode"])) for row in disk["on_disk"]}
    _, series = locate_series(data_dir, platform, slug)
    if isinstance(series, DropoutSeries):
        season = series.sources[source_id].seasons[season_id]
        raw = [
            DropoutListing(url=row["url"], title=row["title"], dropout_episode=int(row["episode"]))
            for row in listings
        ]
        episodes = dropout_episode_rows(season, raw, on_disk=on_disk)
    else:
        assert isinstance(series, YoutubeSeries)
        playlist = PlaylistInfo(
            playlist_id="cached",
            title=series.name,
            description="",
            channel=series.name,
            channel_id="",
            thumbnail_url=None,
            episodes=[
                EpisodeInfo(
                    video_id=row["identity"],
                    title=row["title"],
                    description="",
                    playlist_index=int(row["episode"]),
                    webpage_url=row["url"],
                )
                for row in listings
            ],
        )
        season_data = dict(sources[source_id]["seasons"][season_id])
        if listings:
            season_data["to_season"] = listings[0].get("destination_season")
        episodes = youtube_episode_rows(season_data, playlist, on_disk=on_disk)
    if disk["status"] != "ready":
        for row in episodes:
            if row["status"] in {"missing", "downloaded"}:
                row["status"] = "unknown"
    return {
        "episodes": episodes,
        "on_disk": disk["on_disk"],
        "status": disk["status"],
        "stale": disk["stale"],
        "error": disk["error"],
        "refresh_required": disk["stale"],
    }


def latest_plan(
    data_dir: Path,
    environ: Mapping[str, str],
    store: JobStore,
    *,
    force: bool = False,
    create: bool = False,
) -> dict[str, Any] | None:
    sources: dict[str, dict[str, Any]] = {}
    revisions: list[tuple[str, str, str]] = []
    timestamps: list[str] = []
    views: list[dict[str, Any]] = []
    for record in store.views():
        platform, slug = record["platform"], record["slug"]
        view = _view(record)
        if view is None:
            continue
        try:
            _loc, manifest_series = locate_series(data_dir, platform, slug)
        except KeyError:
            continue
        try:
            plan = plan_variant(view, force=force, create=create)
            current = _current(data_dir, environ, platform, slug, record)
        except (ValueError, KeyError, TypeError):
            continue
        # A failed or expired refresh keeps the last good catalog usable as a
        # stale queue. Manifest/source/library-setting changes still block it.
        if not current and record.get("last_success_at"):
            try:
                from yt_dlp_emby.server.services import current_configuration_revision

                current = (
                    view.get("config_revision")
                    == current_configuration_revision(data_dir, environ, platform, slug)
                    and view.get("source_signature") == source_signature(manifest_series)
                    and view.get("context_signature")
                    == configuration_context_signature(data_dir, environ, platform)
                )
            except (OSError, ValueError, KeyError, ConfigError):
                current = False
        if not current:
            for block in plan["sources"].values():
                for row in block.get("items", []):
                    if row.get("action") in {"download", "replace", "rename", "remove"}:
                        row["action"] = "blocked"
                        row["blocked_reason"] = "Refresh required"
        for name, block in plan["sources"].items():
            combined = sources.setdefault(
                name, {"ok": True, "error": None, "seasons": [], "items": []}
            )
            combined["ok"] = combined["ok"] and current and bool(block.get("ok"))
            if not current or block.get("error"):
                combined["error"] = block.get("error") or "Some targets require Refresh"
            combined["items"].extend(block.get("items", []))
            combined["seasons"].extend(block.get("seasons", []))
        revisions.append((platform, slug, plan["revision"] + ("" if current else ":stale")))
        if record.get("last_success_at"):
            timestamps.append(record["last_success_at"])
        views.append(
            {
                "platform": platform,
                "slug": slug,
                "view": view,
                "current": current,
                "stale": (
                    cache_is_stale(record)
                    or record.get("freshness") != "ready"
                    or bool(getattr(manifest_series, "tvdb_id", None))
                    and cache_part_is_stale(record, "sonarr")
                    or bool(view.get("sonarr_error"))
                ),
                "error": _error_text(record.get("error")) or _error_text(view.get("sonarr_error")),
            }
        )
    if not revisions:
        return None
    revision = hashlib.sha256(
        json.dumps(
            {"views": sorted(revisions), "force": force, "create": create}, sort_keys=True
        ).encode()
    ).hexdigest()
    executable = any(
        row.get("action") in {"download", "replace", "rename", "remove"}
        for block in sources.values()
        for row in block["items"]
    )
    all_current = all(row["current"] for row in views)
    unavailable = any(
        (row["view"].get("disk") or {}).get("status") == "unavailable" for row in views
    )
    readiness = "ready" if executable or all_current else "unavailable" if unavailable else "stale"
    return {
        "plan_id": f"plan_{revision[:24]}",
        "revision": revision,
        "generated_at": max(timestamps, default=None),
        "force": force,
        "readiness": readiness,
        "stale": any(row["stale"] for row in views),
        "cache_errors": [
            {"platform": row["platform"], "slug": row["slug"], "error": row["error"]}
            for row in views
            if row.get("error")
        ],
        "sources": sources,
    }


def latest_queue(
    data_dir: Path, environ: Mapping[str, str], store: JobStore
) -> dict[str, Any] | None:
    """Return only missing episodes from the last good cached listings/inventory."""
    hydrate_catalog_cache(data_dir, store)
    cached = latest_plan(data_dir, environ, store, force=False, create=True)
    if cached is None:
        return None
    for block in cached["sources"].values():
        block["items"] = [row for row in block.get("items", []) if row.get("action") == "download"]
        block["seasons"] = [
            season for season in block.get("seasons", []) if int(season.get("download", 0)) > 0
        ]
        for season in block["seasons"]:
            season["skip"] = 0
            season["replace"] = 0
            season["rename"] = 0
            season["remove"] = 0
    cached["actions"] = [
        row for block in cached["sources"].values() for row in block.get("items", [])
    ]
    return cached


def hydrate_catalog_cache(data_dir: Path, store: JobStore) -> None:
    """Restore durable `/data/cache` snapshots into the fast indexed job store."""
    from yt_dlp_emby.server.services import plan_variant

    existing = {(row["platform"], row["slug"]) for row in store.views()}
    for platform in ("youtube", "dropout"):
        for path in (data_dir / "cache" / platform).glob("*.json"):
            try:
                snapshot = json.loads(path.read_text(encoding="utf-8"))
                slug = str(snapshot.get("slug") or "")
                view = snapshot.get("view")
                if (
                    not slug
                    or (platform, slug) in existing
                    or not isinstance(view, dict)
                    or snapshot.get("version") != 1
                ):
                    continue
                plan = plan_variant(view, create=True)
                fetched = str(snapshot.get("fetched_at") or "") or None
                store.put_view(
                    platform,
                    slug,
                    {"view": view},
                    plan,
                    str(plan.get("revision") or ""),
                    "ready",
                    fetched or "",
                    fetched,
                )
                existing.add((platform, slug))
            except (OSError, ValueError, TypeError, KeyError):
                continue


def executable_selection(
    data_dir: Path,
    environ: Mapping[str, str],
    store: JobStore,
    plan_id: str,
    ids: list[str],
    *,
    force: bool = False,
    create: bool = False,
) -> dict[str, Any]:
    plan = latest_plan(data_dir, environ, store, force=force, create=create)
    if plan is None or plan["plan_id"] != plan_id:
        raise ValueError("PLAN_STALE")
    rows = {row["id"]: row for block in plan["sources"].values() for row in block["items"]}
    if (
        not ids
        or len(set(ids)) != len(ids)
        or any(
            value not in rows
            or rows[value]["action"] not in {"download", "replace", "rename", "remove"}
            for value in ids
        )
    ):
        raise ValueError("PLAN_STALE")
    targets = {(rows[value]["platform"], rows[value]["slug"]) for value in ids}
    return {
        "plan_id": plan_id,
        "selected_actions": [rows[value] for value in ids],
        "cached_views": [
            {"platform": platform, "slug": slug, "view": _view(store.get_view(platform, slug))}
            for platform, slug in sorted(targets)
        ],
    }


def replan_cached(
    data_dir: Path, environ: Mapping[str, str], store: JobStore, platform: str, slug: str
) -> None:
    """Reapply mapping/filter edits to cached provider rows, with no refresh I/O."""
    record = store.get_view(platform, slug)
    view = _view(record)
    if not record or not view or record.get("freshness") != "ready":
        return
    _, series = locate_series(data_dir, platform, slug)
    if view.get("source_signature") != source_signature(series) or view.get(
        "context_signature"
    ) != configuration_context_signature(data_dir, environ, platform):
        store.record_view_attempt(
            platform, slug, "Source or library settings changed; Refresh required"
        )
        return
    mapped: list[dict[str, Any]] = []
    for raw in view.get("provider_listings", []):
        row = ProviderListing(**raw)
        if isinstance(series, DropoutSeries):
            if row.source_index >= len(series.sources) or row.season_index >= len(
                series.sources[row.source_index].seasons
            ):
                store.record_view_attempt(
                    platform, slug, "Source configuration changed; Refresh required"
                )
                return
            season = series.sources[row.source_index].seasons[row.season_index]
            if season.dropout != row.source_season:
                store.record_view_attempt(
                    platform, slug, "Source configuration changed; Refresh required"
                )
                return
            target = resolve_emby_target(
                DropoutListing(url=row.url, title=row.title, dropout_episode=row.episode), season
            )
            skipped = (
                target == "skip"
                or not season.enabled
                or (season.only_episodes is not None and row.episode not in season.only_episodes)
            )
            destination, episode, title = (
                target if isinstance(target, tuple) else (None, None, None)
            )
            row = replace(
                row,
                destination_season=destination,
                mapped_episode=episode,
                mapped_title=title,
                enabled=season.enabled,
                skipped=skipped,
                season_title=season.title,
            )
        else:
            if row.source_index >= len(series.playlists):
                store.record_view_attempt(
                    platform, slug, "Source configuration changed; Refresh required"
                )
                return
            source = series.playlists[row.source_index]
            row = replace(
                row,
                destination_season=source.season
                if source.season is not None
                else row.destination_season,
                skipped=row.identity in source.skip or not source.enabled,
                enabled=source.enabled,
                season_title=source.title,
            )
        mapped.append(asdict(row))
    from yt_dlp_emby.server.services import configuration_revisions, current_configuration_revision

    view.update(configuration_revisions(data_dir, environ, platform, slug))
    view["provider_listings"] = mapped
    view["listing_revision"] = hashlib.sha256(
        json.dumps(mapped, sort_keys=True).encode()
    ).hexdigest()
    view["config_revision"] = current_configuration_revision(data_dir, environ, platform, slug)
    plan = plan_variant(view)
    view["plan_id"] = plan["plan_id"]
    store.put_view(
        platform,
        slug,
        {"view": view},
        plan,
        plan["revision"],
        "ready",
        record["last_attempt_at"],
        record["last_success_at"],
        record["error"],
    )
