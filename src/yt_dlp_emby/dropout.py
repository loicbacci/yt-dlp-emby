"""Download Dropout.tv seasons into an existing Emby/TVDB library (no NFO)."""

from __future__ import annotations

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

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
from yt_dlp_emby.log import RunStats, error, format_dry_run_row, format_elapsed, format_unit_plan
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
) -> tuple[int, int, str] | None:
    for remap in season.remap:
        if remap.dropout_episode == listing.dropout_episode:
            return remap.to_season, remap.to_episode, remap.title or listing.title
    if season.to_season is not None:
        return season.to_season, listing.dropout_episode, listing.title
    if season.dropout is not None:
        return season.dropout, listing.dropout_episode, listing.title
    return None


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
        (series, season)
        for series in manifest.series
        for season in series.seasons
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
    try:
        for series, season in seasons:
            series_path = settings.library / series.path
            page = season_page_url(series, season)
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
                        f"{dest_dir.name}/",
                        title_note,
                    )
                )
            last_series = note_series(settings, series.name, last_series)
            note(
                settings,
                format_season_plan(
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
                ),
            )
            print_work_rows(settings, work_rows)
    except DropoutAuthError as exc:
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
