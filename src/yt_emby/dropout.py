"""Download Dropout.tv seasons into an existing Emby/TVDB library (no NFO)."""

from __future__ import annotations

import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

from yt_emby.auth import DropoutAuthError, auth_error_from_exception
from yt_emby.cache import (
    dropout_listings_from_cache,
    dropout_listings_to_cache,
    load_dropout_season_cache,
    save_dropout_season_cache,
)
from yt_emby.config import ConfigError, Settings
from yt_emby.download import download_video, promote_episode
from yt_emby.dropout_manifest import (
    DropoutManifest,
    DropoutSeason,
    DropoutSeries,
    season_page_url,
)
from yt_emby.extract import DropoutListing, extract_dropout_season
from yt_emby.library import (
    emby_code,
    episode_stem,
    episode_title_from_filename,
    find_episode_mkv,
    season_folder_name,
    titles_match,
)
from yt_emby.log import RunStats, error, format_dry_run_row, info, warn
from yt_emby.progress import DownloadProgress
from yt_emby.style import bold, dim, green, red, yellow
from yt_emby.sync import move_episode_files

DROPOUT_SUBS = ["all"]


def emby_season_dir(series: Path, season: int) -> Path:
    if season == 0:
        return series / "Specials"
    return series / season_folder_name(season)


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
) -> str:
    key = f"season {season.dropout}" if season.dropout is not None else "season"
    dest = season_dest_label(season)
    skip_part = dim(f"{skip} skip")
    download_part = (
        green(f"{download} download") if download else dim(f"{download} download")
    )
    line = f"  {key} → {dest}  {skip_part}  {download_part}"
    if unmapped:
        line += f"  {red(f'{unmapped} unmapped')}"
    if retitled:
        line += f"  {yellow(f'{retitled} title differs')}"
    return line


def _log(settings: Settings, message: str) -> None:
    if settings.show_steps:
        info(message)


def _note(settings: Settings, message: str) -> None:
    if settings.show_summary:
        info(message)


def _warn(settings: Settings, message: str) -> None:
    if settings.show_warnings:
        warn(message)


def _finish(settings: Settings, stats: RunStats) -> int:
    if settings.show_summary:
        stats.recap()
        info("")
        info(stats.summary())
    if stats.interrupted:
        return 130
    return 1 if stats.failed else 0


def resolve_emby_target(
    listing: DropoutListing,
    season: DropoutSeason,
) -> tuple[int, int] | None:
    for remap in season.remap:
        if remap.dropout_episode == listing.dropout_episode:
            return remap.to_season, remap.to_episode
    if season.to_season is not None:
        return season.to_season, listing.dropout_episode
    if season.dropout is not None:
        return season.dropout, listing.dropout_episode
    return None


def planned_stem(
    series: DropoutSeries,
    listing: DropoutListing,
    to_season: int,
    to_episode: int,
) -> str:
    return episode_stem(series.name, to_season, to_episode, listing.title)


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
            _log(settings, f"Created series folder {path}")
        return
    message = "Series folder(s) do not exist (pass --create to create them):\n  " + listing
    if settings.dry_run:
        _warn(settings, message)
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
        return _finish(settings, stats)


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
    ensure_series_dirs(manifest, settings, create=create)
    if settings.cookiefile:
        _log(settings, f"Using cookies file {settings.cookiefile}")
    extract = extract_fn or extract_dropout_season
    download = download_fn or download_video
    jobs: list[tuple[DropoutSeries, DropoutListing, int, int, Path, str, Path | None]] = []
    seasons = [
        (series, season)
        for series in manifest.series
        for season in series.seasons
    ]
    cached_seasons = load_dropout_season_cache(settings.library)
    last_series: str | None = None
    try:
        for series, season in seasons:
            series_path = settings.library / series.path
            page = season_page_url(series, season)
            listings = (
                None
                if settings.force_refetch
                else dropout_listings_from_cache(cached_seasons.get(page))
            )
            if listings is None:
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
                save_dropout_season_cache(settings.library, cached_seasons)
            skip = 0
            queued = 0
            unmapped = 0
            retitled = 0
            work_rows: list[tuple[str, str, str, str, str | None]] = []
            for listing in listings:
                target = resolve_emby_target(listing, season)
                if target is None:
                    unmapped += 1
                    work_rows.append(
                        (
                            "unmapped",
                            f"E{listing.dropout_episode}",
                            listing.title,
                            "",
                            None,
                        )
                    )
                    continue
                to_season, to_episode = target
                dest_dir = emby_season_dir(series_path, to_season)
                stem = planned_stem(series, listing, to_season, to_episode)
                existing = find_episode_mkv(dest_dir, to_season, to_episode)
                title_note = None
                if existing is not None and not titles_match(
                    episode_title_from_filename(existing.name), listing.title
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
                    (
                        action,
                        emby_code(to_season, to_episode),
                        listing.title,
                        f"{dest_dir.name}/",
                        title_note,
                    )
                )
            if last_series != series.name:
                if last_series is not None:
                    _note(settings, "")
                _note(settings, bold(series.name))
                last_series = series.name
            _note(
                settings,
                format_season_plan(
                    season,
                    skip=skip,
                    download=queued,
                    unmapped=unmapped,
                    retitled=retitled,
                ),
            )
            for action, code, title, folder, title_note in work_rows:
                if action == "skip" and not settings.verbose:
                    continue
                if action == "download" and not settings.dry_run:
                    continue
                _note(
                    settings,
                    "    " + format_dry_run_row(action, code, title, folder),
                )
                if title_note and settings.verbose:
                    _note(settings, "              " + yellow(title_note))
    except DropoutAuthError as exc:
        error(str(exc))
        stats.failed += 1
        stats.failures.append(("listing", str(exc)))
        return _finish(settings, stats)

    download_jobs = [job for job in jobs if force or job[6] is None]
    stats.skipped = len(jobs) - len(download_jobs)

    if settings.dry_run:
        stats.downloaded = len(download_jobs)
        return _finish(settings, stats)

    if download_jobs:
        _log(settings, f"Downloading {len(download_jobs)} of {len(jobs)} episodes")
    elif jobs:
        _log(settings, f"Skipping {stats.skipped} existing file(s)")

    if not download_jobs:
        return _finish(settings, stats)

    staging_parent = str(settings.staging) if settings.staging else None
    if settings.staging:
        settings.staging.mkdir(parents=True, exist_ok=True)
        _log(settings, f"Staging downloads on local disk: {settings.staging}")
    else:
        _log(settings, "Staging downloads in the system temp directory")

    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    with tempfile.TemporaryDirectory(prefix="yt-emby-dropout-", dir=staging_parent) as tmp:
        work_dir = Path(tmp)
        for i, (series, listing, to_season, to_episode, dest_dir, stem, existing) in enumerate(
            download_jobs, start=1
        ):
            stats.remaining = len(download_jobs) - i + 1
            eta = stats.eta(len(download_jobs) - i)
            extra = f"  ETA {eta}" if eta else ""
            local_stem = work_dir / stem
            dest_stem = dest_dir / stem
            _log(settings, f"[{i}/{len(download_jobs)}] Downloading {stem}{extra}")
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
                return _finish(settings, stats)
            except Exception as exc:
                auth = auth_error_from_exception(listing.url, exc)
                if auth is not None:
                    error(str(auth))
                    stats.failed += 1
                    stats.failures.append((stem, str(auth)))
                    stats.remaining = len(download_jobs) - i
                    return _finish(settings, stats)
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
            _log(settings, f"[{i}/{len(download_jobs)}] Copying to library")
            copy_progress = DownloadProgress(enabled=settings.show_progress)
            promote_episode(local_stem, dest_stem, copy_progress)
            if existing is not None and existing.stem != stem:
                old_dest = settings.old_dir / series.name / stamp
                move_episode_files(dest_dir, existing.stem, old_dest)
                _log(settings, f"Moved previous title to {old_dest}")
            stats.mark_download(time.monotonic() - started)
            stats.downloaded += 1
            stats.remaining = len(download_jobs) - i

    return _finish(settings, stats)
