"""Download Dropout.tv seasons into an existing Emby/TVDB library (no NFO)."""

from __future__ import annotations

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from yt_dlp_emby.auth import DropoutAuthError, auth_error_from_exception
from yt_dlp_emby.cache import (
    dropout_cache_path,
    dropout_listings_from_cache,
    dropout_listings_to_cache,
    load_dropout_season_cache,
    migrate_dropout_season_cache,
    save_dropout_season_cache,
)
from yt_dlp_emby.config import ConfigError, Settings
from yt_dlp_emby.download import cleanup_stale_staging, download_video, mark_live_staging, promote_episode
from yt_dlp_emby.dropout_manifest import (
    DropoutManifest,
    DropoutSeason,
    DropoutSeries,
    season_page_url,
)
from yt_dlp_emby.extract import DropoutListing, extract_dropout_season
from yt_dlp_emby.job import WorkRow, finish, log_step, note, note_series, print_work_rows, warn_if
from yt_dlp_emby.library import (
    emby_code,
    episode_stem,
    episode_title_from_filename,
    index_episode_mkvs,
    season_dir,
    season_folder_name,
    titles_match,
)
from yt_dlp_emby.log import RunStats, error, format_elapsed, format_unit_plan
from yt_dlp_emby.progress import DownloadProgress
from yt_dlp_emby.style import dim
from yt_dlp_emby.sync import move_episode_files

DROPOUT_SUBS = ["all"]


def emby_season_dir(series: Path, season: int) -> Path:
    return season_dir(series, season)


def season_dest_label(season: DropoutSeason) -> str:
    dests: set[int] = set()
    if season.to_season is not None:
        dests.add(season.to_season)
    elif season.dropout is not None:
        dests.add(season.dropout)
    for remap in season.remap:
        if remap.to_season is not None:
            dests.add(remap.to_season)
    if len(dests) == 1:
        number = next(iter(dests))
        return "Specials" if number == 0 else season_folder_name(number)
    if dests:
        return "remap"
    return "?"


def format_season_plan(
    season: DropoutSeason,
    *,
    skip: int,
    download: int,
    unmapped: int,
    retitled: int = 0,
    omitted: int = 0,
    listing_source: str | None = None,
    listing_seconds: float | None = None,
    disk_seconds: float | None = None,
    debug: bool = False,
) -> str:
    key = f"season {season.dropout}" if season.dropout is not None else "season"
    extras: dict[str, int] = {}
    if unmapped:
        extras["unmapped"] = unmapped
    if omitted:
        extras["omitted"] = omitted
    if retitled:
        extras["title differs"] = retitled
    return format_unit_plan(
        key,
        dest=season_dest_label(season),
        skip=skip,
        download=download,
        extras=extras,
        listing_source=listing_source,
        listing_seconds=listing_seconds,
        disk_seconds=disk_seconds,
        debug=debug,
    )


def resolve_emby_target(
    listing: DropoutListing,
    season: DropoutSeason,
) -> tuple[int, int, str] | Literal["skip"] | None:
    for remap in season.remap:
        if remap.dropout_episode == listing.dropout_episode:
            if remap.skip:
                return "skip"
            assert remap.to_season is not None and remap.to_episode is not None
            return remap.to_season, remap.to_episode, remap.title or listing.title
    if season.to_season is not None:
        return season.to_season, listing.dropout_episode, listing.title
    if season.dropout is not None:
        return season.dropout, listing.dropout_episode, listing.title
    return None


def layout_origin(
    season: DropoutSeason,
    listing: DropoutListing,
    to_season: int,
    to_episode: int,
) -> str | None:
    if season.dropout == to_season and listing.dropout_episode == to_episode:
        return None
    if season.dropout is not None:
        return f"season {season.dropout} E{listing.dropout_episode:02d}"
    if listing.dropout_episode != to_episode:
        return f"E{listing.dropout_episode:02d}"
    return None


def layout_series_groups(
    series_list: tuple[DropoutSeries, ...],
) -> dict[tuple[str, str], tuple[str, str]]:
    """Map manifest (name, path) to a shared layout group key and header label."""
    if not series_list:
        return {}
    parent = list(range(len(series_list)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(left: int, right: int) -> None:
        root_left, root_right = find(left), find(right)
        if root_left != root_right:
            parent[root_right] = root_left

    by_name: dict[str, list[int]] = {}
    by_path: dict[str, list[int]] = {}
    for index, series in enumerate(series_list):
        by_name.setdefault(series.name.casefold(), []).append(index)
        by_path.setdefault(series.path.casefold(), []).append(index)

    for indices in by_name.values():
        base = indices[0]
        for other in indices[1:]:
            union(base, other)
    for indices in by_path.values():
        base = indices[0]
        for other in indices[1:]:
            union(base, other)

    members: dict[int, list[DropoutSeries]] = {}
    for index, series in enumerate(series_list):
        members.setdefault(find(index), []).append(series)

    grouped: dict[tuple[str, str], tuple[str, str]] = {}
    for root, group in members.items():
        paths = {item.path for item in group}
        names = {item.name for item in group}
        if len(paths) == 1:
            label = next(iter(paths))
        elif len(names) == 1:
            label = next(iter(names))
        else:
            label = group[0].path
        group_key = str(root)
        for item in group:
            grouped[(item.name, item.path)] = (group_key, label)
    return grouped


def _dest_sort_key(season: int | None) -> tuple[int, int]:
    if season is None:
        return (2, 0)
    if season == 0:
        return (1, 0)
    return (0, season)


def print_series_layout(settings: Settings, rows: list[WorkRow]) -> None:
    groups: dict[int | None, list[WorkRow]] = {}
    for row in rows:
        groups.setdefault(row.dest_season, []).append(row)
    dests = sorted(groups, key=_dest_sort_key)
    for index, dest in enumerate(dests):
        if index:
            note(settings, "")
        grouped = groups[dest]
        if dest is None:
            note(settings, "  unmapped")
            print_work_rows(settings, grouped)
            continue
        skip = sum(1 for row in grouped if row.action == "skip")
        download = sum(1 for row in grouped if row.action == "download")
        retitled = sum(1 for row in grouped if row.note)
        extras = {"title differs": retitled} if retitled else None
        label = "Specials" if dest == 0 else season_folder_name(dest)
        note(
            settings,
            format_unit_plan(label, skip=skip, download=download, extras=extras),
        )
        print_work_rows(settings, grouped)


def planned_stem(
    series: DropoutSeries,
    listing: DropoutListing,
    to_season: int,
    to_episode: int,
    title: str | None = None,
) -> str:
    return episode_stem(series.name, to_season, to_episode, title or listing.title)


def ensure_series_dirs(manifest: DropoutManifest, settings: Settings, *, create: bool) -> None:
    missing = [
        settings.library / series.path
        for series in manifest.series
        if not (settings.library / series.path).is_dir()
    ]
    if not missing:
        return
    listing = "\n  ".join(str(path) for path in missing)
    if create:
        for path in missing:
            path.mkdir(parents=True, exist_ok=True)
            log_step(settings, f"Created series folder {path}")
        return
    message = "Series folder(s) do not exist (pass --create to create them):\n  " + listing
    if settings.dry_run:
        warn_if(settings, message)
        return
    raise ConfigError(message)


def run_dropout(
    manifest: DropoutManifest,
    settings: Settings,
    *,
    force: bool = False,
    create: bool = False,
    format_selector: str | None = None,
    extract_fn=None,
    download_fn=None,
) -> int:
    stats = RunStats(dry_run=settings.dry_run)
    try:
        return _run_dropout(
            manifest,
            settings,
            stats,
            force=force,
            create=create,
            format_selector=format_selector,
            extract_fn=extract_fn,
            download_fn=download_fn,
        )
    except KeyboardInterrupt:
        stats.interrupted = True
        error("interrupted")
        return finish(settings, stats)


def _run_dropout(
    manifest: DropoutManifest,
    settings: Settings,
    stats: RunStats,
    *,
    force: bool,
    create: bool,
    format_selector: str | None,
    extract_fn,
    download_fn,
) -> int:
    stale = cleanup_stale_staging(settings.staging)
    if stale:
        log_step(settings, f"Removed {stale} leftover staging path(s)")
    ensure_series_dirs(manifest, settings, create=create)
    if settings.cookiefile:
        log_step(settings, f"Using cookies file {settings.cookiefile}")
    extract = extract_fn or extract_dropout_season
    download = download_fn or download_video
    jobs: list[tuple[DropoutSeries, DropoutListing, int, int, Path, str, Path | None]] = []
    seasons = [
        (series, source, season)
        for series in manifest.series
        for source in series.sources
        for season in source.seasons
    ]
    cache_path = dropout_cache_path(manifest.path)
    cache_started = time.monotonic()
    moved_from = migrate_dropout_season_cache(cache_path, settings.library)
    cached_seasons = load_dropout_season_cache(cache_path)
    cache_load = time.monotonic() - cache_started
    if moved_from:
        note(settings, dim(f"moved listing cache from {moved_from}"))
    if settings.debug:
        note(
            settings,
            dim(
                f"listing cache  {cache_path}  {len(cached_seasons)} seasons  "
                f"{format_elapsed(cache_load)}"
            ),
        )
    mkv_indexes: dict[Path, dict[tuple[int, int], Path]] = {}
    last_series: str | None = None
    layout_rows: list[WorkRow] = []
    layout_plans: list[str] = []
    layout_groups = layout_series_groups(manifest.series) if settings.layout else {}
    last_layout_group: str | None = None

    def flush_layout() -> None:
        if settings.debug:
            for plan in layout_plans:
                note(settings, plan)
        print_series_layout(settings, layout_rows)
        layout_rows.clear()
        layout_plans.clear()

    try:
        for series, source, season in seasons:
            if settings.layout:
                group_key, group_label = layout_groups[(series.name, series.path)]
                if last_layout_group is not None and last_layout_group != group_key:
                    flush_layout()
                if last_layout_group != group_key:
                    last_series = note_series(settings, group_label, last_series)
                    last_layout_group = group_key
            series_path = settings.library / series.path
            page = season_page_url(source, season)
            listing_started = time.monotonic()
            listings = (
                None
                if settings.force_refetch
                else dropout_listings_from_cache(cached_seasons.get(page))
            )
            listing_source = "cached"
            if listings is None:
                listing_source = "fetch"
                try:
                    listings = extract(
                        page,
                        cookies_from_browser=settings.cookies_from_browser,
                        cookiefile=str(settings.cookiefile) if settings.cookiefile else None,
                        progress=settings.show_progress,
                        verbose=settings.verbose,
                        emit_warnings=settings.show_warnings,
                    )
                except DropoutAuthError:
                    raise
                except Exception as exc:
                    auth = auth_error_from_exception(page, exc)
                    if auth is not None:
                        raise auth from exc
                    raise
                cached_seasons[page] = dropout_listings_to_cache(listings)
                save_dropout_season_cache(cache_path, cached_seasons)
            listing_seconds = time.monotonic() - listing_started
            skip = 0
            queued = 0
            unmapped = 0
            retitled = 0
            omitted = 0
            disk_seconds = 0.0
            work_rows: list[WorkRow] = []
            allowed = set(season.only_episodes) if season.only_episodes else None
            for listing in listings:
                if allowed is not None and listing.dropout_episode not in allowed:
                    omitted += 1
                    continue
                target = resolve_emby_target(listing, season)
                if target == "skip":
                    omitted += 1
                    continue
                if target is None:
                    unmapped += 1
                    work_rows.append(
                        WorkRow(
                            "unmapped",
                            f"E{listing.dropout_episode}",
                            listing.title,
                            "",
                        )
                    )
                    continue
                to_season, to_episode, title = target
                dest_dir = emby_season_dir(series_path, to_season)
                stem = planned_stem(series, listing, to_season, to_episode, title)
                if dest_dir not in mkv_indexes:
                    disk_started = time.monotonic()
                    mkv_indexes[dest_dir] = index_episode_mkvs(dest_dir)
                    disk_seconds += time.monotonic() - disk_started
                existing = mkv_indexes[dest_dir].get((to_season, to_episode))
                title_note = None
                if existing is not None and not titles_match(
                    episode_title_from_filename(existing.name), title
                ):
                    retitled += 1
                    if force:
                        title_note = f"title differs  {existing.name} -> {stem}.mkv"
                    else:
                        title_note = f"title differs  keeping {existing.name}"
                if existing is not None and not force:
                    skip += 1
                    action = "skip"
                else:
                    queued += 1
                    action = "download"
                jobs.append(
                    (series, listing, to_season, to_episode, dest_dir, stem, existing)
                )
                work_rows.append(
                    WorkRow(
                        action,
                        emby_code(to_season, to_episode),
                        title,
                        "" if settings.layout else f"{dest_dir.name}/",
                        title_note,
                        dest_season=to_season,
                        origin=(
                            layout_origin(season, listing, to_season, to_episode)
                            if settings.layout
                            else None
                        ),
                    )
                )
            plan = format_season_plan(
                season,
                skip=skip,
                download=queued,
                unmapped=unmapped,
                retitled=retitled,
                omitted=omitted,
                listing_source=listing_source,
                listing_seconds=listing_seconds,
                disk_seconds=disk_seconds,
                debug=settings.debug,
            )
            if settings.layout:
                layout_rows.extend(work_rows)
                layout_plans.append(plan)
            else:
                last_series = note_series(settings, series.name, last_series)
                note(settings, plan)
                print_work_rows(settings, work_rows)
        if settings.layout:
            flush_layout()
    except DropoutAuthError as exc:
        if settings.layout:
            flush_layout()
        error(str(exc))
        stats.failed += 1
        stats.failures.append(("listing", str(exc)))
        return finish(settings, stats)

    download_jobs = [job for job in jobs if force or job[6] is None]
    stats.skipped = len(jobs) - len(download_jobs)

    if settings.dry_run:
        stats.downloaded = len(download_jobs)
        return finish(settings, stats)

    if download_jobs:
        log_step(settings, f"Downloading {len(download_jobs)} of {len(jobs)} episodes")
    elif jobs:
        log_step(settings, f"Skipping {stats.skipped} existing file(s)")

    if not download_jobs:
        return finish(settings, stats)

    staging_parent = str(settings.staging) if settings.staging else None
    if settings.staging:
        settings.staging.mkdir(parents=True, exist_ok=True)
        log_step(settings, f"Staging downloads on local disk: {settings.staging}")
    else:
        log_step(settings, "Staging downloads in the system temp directory")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    with tempfile.TemporaryDirectory(
        prefix="yt-dlp-emby-dropout-", dir=staging_parent, ignore_cleanup_errors=True
    ) as tmp:
        work_dir = Path(tmp)
        mark_live_staging(work_dir)
        for i, (series, listing, to_season, to_episode, dest_dir, stem, existing) in enumerate(
            download_jobs, start=1
        ):
            stats.remaining = len(download_jobs) - i + 1
            eta = stats.eta(len(download_jobs) - i)
            extra = f"  ETA {eta}" if eta else ""
            local_stem = work_dir / stem
            dest_stem = dest_dir / stem
            log_step(settings, f"[{i}/{len(download_jobs)}] Downloading {stem}{extra}")
            started = time.monotonic()
            try:
                info_dict = download(
                    listing.url,
                    local_stem,
                    settings,
                    format_selector=format_selector,
                    subtitleslangs=DROPOUT_SUBS,
                )
            except DropoutAuthError as exc:
                error(str(exc))
                stats.failed += 1
                stats.failures.append((stem, str(exc)))
                stats.remaining = len(download_jobs) - i
                return finish(settings, stats)
            except Exception as exc:
                auth = auth_error_from_exception(listing.url, exc)
                if auth is not None:
                    error(str(auth))
                    stats.failed += 1
                    stats.failures.append((stem, str(auth)))
                    stats.remaining = len(download_jobs) - i
                    return finish(settings, stats)
                message = str(exc)
                error(f"download failed for {stem}: {message}")
                stats.failed += 1
                stats.failures.append((stem, message))
                continue
            if not info_dict or not info_dict.get("id"):
                message = "download returned no metadata"
                error(f"{message} for {stem}")
                stats.failed += 1
                stats.failures.append((stem, message))
                continue
            log_step(settings, f"[{i}/{len(download_jobs)}] Copying to library")
            copy_progress = DownloadProgress(enabled=settings.show_progress)
            promote_episode(local_stem, dest_stem, copy_progress)
            if existing is not None and existing.stem != stem:
                old_dest = settings.old_dir / series.name / stamp
                move_episode_files(dest_dir, existing.stem, old_dest)
                log_step(settings, f"Moved previous title to {old_dest}")
            stats.mark_download(time.monotonic() - started)
            stats.downloaded += 1
            stats.remaining = len(download_jobs) - i

    return finish(settings, stats)
