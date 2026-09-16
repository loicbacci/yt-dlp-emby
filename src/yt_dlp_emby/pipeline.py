"""Orchestrate extract, sync, download, NFO, and artwork."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import tempfile
import time
from pathlib import Path

from yt_dlp_emby.cache import (
    episode_from_cache,
    episode_to_cache,
    hydrate_playlist,
    load_cache,
    save_cache,
)
from yt_dlp_emby.config import Settings
from yt_dlp_emby.download import (
    TARGET_HEIGHT,
    YoutubeAuthError,
    cleanup_stale_staging,
    download_video,
    mark_live_staging,
    promote_episode,
    video_height,
)
from yt_dlp_emby.extract import (
    ChannelArt,
    EpisodeInfo,
    PlaylistInfo,
    episode_from_info,
    extract_channel_art,
    extract_playlist,
    extract_video,
    with_episode,
)
from yt_dlp_emby.images import download_image
from yt_dlp_emby.job import WorkRow, finish, log_step, note, note_series, print_work_rows, warn_if
from yt_dlp_emby.library import (
    EpisodeRecord,
    LibraryIndex,
    PlaylistRecord,
    assign_season,
    emby_code,
    episode_stem,
    load_index,
    media_exists,
    save_index,
    season_dir,
    series_dir,
)
from yt_dlp_emby.log import RunStats, error, format_unit_plan
from yt_dlp_emby.nfo import write_episode_nfo, write_season_nfo, write_tvshow_nfo
from yt_dlp_emby.progress import DownloadProgress, estimate_media_bytes, format_size_estimate
from yt_dlp_emby.sync import (
    ActionKind,
    SyncAction,
    apply_renames,
    move_episode_files,
    plan_sync,
)
from yt_dlp_emby.youtube_manifest import YoutubeManifest


def _premiered(playlist: PlaylistInfo) -> str | None:
    dates = [ep.upload_date for ep in playlist.episodes if ep.upload_date]
    if not dates:
        return None
    oldest = min(dates)
    return f"{oldest[:4]}-{oldest[4:6]}-{oldest[6:]}"


def _video_url(episode: EpisodeInfo) -> str:
    return episode.webpage_url or f"https://www.youtube.com/watch?v={episode.video_id}"


def write_artwork(
    series: Path,
    season: Path,
    season_number: int,
    playlist: PlaylistInfo,
    art: ChannelArt | None,
    episodes: list[tuple[str, EpisodeInfo]],
) -> None:
    write_series_artwork(series, season, season_number, playlist, art)
    for stem, episode in episodes:
        write_episode_thumb(season, stem, episode)


def write_series_artwork(
    series: Path,
    season: Path,
    season_number: int,
    playlist: PlaylistInfo,
    art: ChannelArt | None,
) -> None:
    if art and art.avatar_url:
        download_image(art.avatar_url, series / "poster.jpg")
    if art and art.banner_url:
        download_image(art.banner_url, series / "fanart.jpg")
    if playlist.thumbnail_url:
        download_image(playlist.thumbnail_url, series / f"season{season_number:02d}-poster.jpg")
        download_image(playlist.thumbnail_url, season / "poster.jpg")


def write_episode_thumb(season: Path, stem: str, episode: EpisodeInfo) -> None:
    if episode.thumbnail_url:
        download_image(episode.thumbnail_url, season / f"{stem}-thumb.jpg")


def _write_series_metadata(
    series: Path,
    season_path: Path,
    playlist: PlaylistInfo,
    index: LibraryIndex,
    season_number: int,
    art: ChannelArt | None,
) -> None:
    named = {record.season: record.title for record in index.playlists.values()}
    plot = (art.description if art and art.description else "") or playlist.description
    write_tvshow_nfo(
        series / "tvshow.nfo",
        title=playlist.channel,
        plot=plot,
        channel_id=playlist.channel_id,
        named_seasons=named,
        premiered=_premiered(playlist),
    )
    write_season_nfo(
        season_path / "season.nfo",
        title=playlist.title,
        plot=playlist.description,
        season=season_number,
    )


def _write_episode_sidecars(
    season_path: Path,
    playlist: PlaylistInfo,
    season_number: int,
    episode: EpisodeInfo,
) -> None:
    stem = episode_stem(playlist.channel, season_number, episode.playlist_index, episode.title)
    write_episode_nfo(
        season_path / f"{stem}.nfo",
        episode=episode,
        season=season_number,
        episode_number=episode.playlist_index,
    )
    write_episode_thumb(season_path, stem, episode)


def _ensure_playlist_record(
    index: LibraryIndex,
    playlist: PlaylistInfo,
    season_number: int,
) -> PlaylistRecord:
    record = index.playlists.get(playlist.playlist_id)
    if record is None:
        record = PlaylistRecord(
            playlist_id=playlist.playlist_id,
            season=season_number,
            title=playlist.title,
            description=playlist.description,
            episodes={},
        )
        index.playlists[playlist.playlist_id] = record
        return record
    record.title = playlist.title
    record.description = playlist.description
    record.season = season_number
    return record


def _upsert_episode(
    index: LibraryIndex,
    playlist: PlaylistInfo,
    season: int,
    episode: EpisodeInfo,
) -> None:
    record = _ensure_playlist_record(index, playlist, season)
    record.episodes[episode.video_id] = EpisodeRecord(
        video_id=episode.video_id,
        episode=episode.playlist_index,
        title=episode.title,
        basename=episode_stem(playlist.channel, season, episode.playlist_index, episode.title),
        duration=episode.duration,
        filesize=episode.filesize,
        upload_date=episode.upload_date,
    )


def _commit_episode(
    series: Path,
    season_path: Path,
    playlist: PlaylistInfo,
    index: LibraryIndex,
    season_number: int,
    episode: EpisodeInfo,
    cache: dict[str, dict],
) -> PlaylistInfo:
    cache[episode.video_id] = episode_to_cache(episode)
    save_cache(series, cache)
    playlist = with_episode(playlist, episode)
    _write_episode_sidecars(season_path, playlist, season_number, episode)
    _upsert_episode(index, playlist, season_number, episode)
    save_index(series, index)
    return playlist


def _upgrade_low_res_actions(
    actions: list[SyncAction],
    season_path: Path,
    ffmpeg: Path,
) -> None:
    for action in actions:
        if action.kind not in {ActionKind.REFRESH, ActionKind.RENAME}:
            continue
        basename = action.new_basename
        if not basename:
            continue
        dest = season_path / f"{basename}.mkv"
        exists = dest.is_file()
        height = video_height(dest, ffmpeg) if exists else None
        if not exists:
            action.kind = ActionKind.ADD
            continue
        if height is None or height >= TARGET_HEIGHT:
            continue
        action.kind = ActionKind.REPLACE
        if not action.old_basename:
            action.old_basename = basename


_ROW_ACTION = {
    ActionKind.ADD: "download",
    ActionKind.REFRESH: "skip",
    ActionKind.REPLACE: "replace",
    ActionKind.RENAME: "rename",
    ActionKind.REMOVE: "remove",
}


@dataclass
class YoutubePlaylistJob:
    url: str
    series_name: str
    series: Path
    season_number: int
    season_path: Path
    playlist: PlaylistInfo
    actions: list[SyncAction]
    listing_seconds: float
    disk_seconds: float


def _action_title(action: SyncAction) -> str:
    if action.live is not None:
        return action.live.title
    if action.stored is not None:
        return action.stored.title
    return action.video_id


def _youtube_plan_counts(actions: list[SyncAction]) -> tuple[int, int, dict[str, int]]:
    counts = Counter(action.kind.value for action in actions)
    skip = counts.get("refresh", 0)
    download = counts.get("add", 0) + counts.get("replace", 0)
    extras: dict[str, int] = {}
    if counts.get("rename"):
        extras["rename"] = counts["rename"]
    if counts.get("remove"):
        extras["remove"] = counts["remove"]
    return skip, download, extras


def _youtube_download_bytes(actions: list[SyncAction]) -> int | None:
    total = 0
    found = False
    for action in actions:
        if action.kind not in {ActionKind.ADD, ActionKind.REPLACE} or action.live is None:
            continue
        nbytes = estimate_media_bytes(
            filesize=action.live.filesize, duration=action.live.duration
        )
        if not nbytes:
            continue
        total += nbytes
        found = True
    return total if found else None


def _tally_youtube_plan(job: YoutubePlaylistJob, stats: RunStats) -> None:
    counts = Counter(action.kind.value for action in job.actions)
    stats.downloaded += counts.get("add", 0) + counts.get("replace", 0)
    stats.skipped += counts.get("refresh", 0) + counts.get("rename", 0)


def _print_youtube_unit(job: YoutubePlaylistJob, settings: Settings) -> None:
    skip, download, extras = _youtube_plan_counts(job.actions)
    note(
        settings,
        format_unit_plan(
            f"season {job.season_number}",
            dest=job.season_path.name,
            skip=skip,
            download=download,
            extras=extras,
            download_bytes=_youtube_download_bytes(job.actions),
            listing_source="listed",
            listing_seconds=job.listing_seconds,
            disk_seconds=job.disk_seconds,
            debug=settings.debug,
        ),
    )
    print_work_rows(
        settings,
        [
            WorkRow(
                _ROW_ACTION.get(action.kind, action.kind.value),
                emby_code(action.season, action.episode or 0),
                _action_title(action),
                f"{job.season_path.name}/",
                size=(
                    estimate_media_bytes(
                        filesize=action.live.filesize, duration=action.live.duration
                    )
                    if action.kind in {ActionKind.ADD, ActionKind.REPLACE} and action.live
                    else None
                ),
            )
            for action in job.actions
        ],
    )


def _cleanup_start(settings: Settings) -> None:
    stale = cleanup_stale_staging(settings.staging)
    if stale:
        log_step(settings, f"Removed {stale} leftover staging path(s)")
    if settings.cookiefile:
        log_step(settings, f"Using cookies file {settings.cookiefile}")


def _prepare_playlist(
    url: str,
    settings: Settings,
    *,
    playlist_items: str | None = None,
    series_folder: str | None = None,
) -> YoutubePlaylistJob:
    if settings.verbose or settings.debug:
        log_step(settings, f"Listing playlist: {url}")
    listing_started = time.monotonic()
    playlist = extract_playlist(
        url,
        playlist_items=playlist_items,
        cookies_from_browser=settings.cookies_from_browser,
        cookiefile=str(settings.cookiefile) if settings.cookiefile else None,
        progress=settings.show_progress,
        verbose=settings.verbose,
        emit_warnings=settings.show_warnings,
    )
    listing_seconds = time.monotonic() - listing_started
    if settings.debug:
        log_step(
            settings,
            f"Found {len(playlist.episodes)} video(s) in "
            f"{playlist.channel} / {playlist.title}",
        )

    disk_started = time.monotonic()
    series_name = series_folder or playlist.channel
    series = series_dir(settings.library, series_name)
    cache = load_cache(series)
    playlist = hydrate_playlist(playlist, cache, force_refetch=settings.force_refetch)
    index = load_index(series)
    if not index.channel_id:
        index.channel_id = playlist.channel_id
        index.channel_name = playlist.channel
    season_number = assign_season(index, playlist.playlist_id, settings.season)
    existing = index.playlists.get(playlist.playlist_id)
    actions = plan_sync(playlist, existing, season_number)
    season_path = season_dir(series, season_number)
    _upgrade_low_res_actions(actions, season_path, settings.ffmpeg)
    return YoutubePlaylistJob(
        url=url,
        series_name=series_name,
        series=series,
        season_number=season_number,
        season_path=season_path,
        playlist=playlist,
        actions=actions,
        listing_seconds=listing_seconds,
        disk_seconds=time.monotonic() - disk_started,
    )


def _fetch_channel_art(playlist: PlaylistInfo, settings: Settings) -> ChannelArt | None:
    if not playlist.channel_id:
        return None
    log_step(settings, "Fetching channel artwork")
    try:
        return extract_channel_art(
            playlist.channel_id,
            cookies_from_browser=settings.cookies_from_browser,
            cookiefile=str(settings.cookiefile) if settings.cookiefile else None,
            progress=settings.show_progress,
            verbose=settings.verbose,
            emit_warnings=settings.show_warnings,
        )
    except Exception as exc:  # noqa: BLE001 — channel art is optional
        warn_if(settings, f"could not fetch channel artwork: {exc}")
        return None


def _keep_listing(listing: EpisodeInfo, fetched: EpisodeInfo) -> EpisodeInfo:
    return replace(
        fetched,
        video_id=listing.video_id,
        title=listing.title,
        playlist_index=listing.playlist_index,
    )


def _resolve_episode(
    episode: EpisodeInfo,
    cache: dict[str, dict],
    settings: Settings,
    *,
    force: bool,
) -> EpisodeInfo:
    if not force and episode.video_id in cache:
        return episode_from_cache(episode, cache[episode.video_id])
    resolved = extract_video(
        _video_url(episode),
        episode.playlist_index,
        cookies_from_browser=settings.cookies_from_browser,
        cookiefile=str(settings.cookiefile) if settings.cookiefile else None,
        verbose=settings.verbose,
        emit_warnings=settings.show_warnings,
    )
    return _keep_listing(episode, resolved)


def _listing_failed(settings: Settings, stats: RunStats, exc: Exception) -> int:
    error(str(exc))
    stats.failed += 1
    stats.failures.append(("listing", str(exc)))
    return finish(settings, stats)


def run_download(
    url: str,
    settings: Settings,
    format_selector: str | None = None,
    *,
    playlist_items: str | None = None,
    series_folder: str | None = None,
) -> int:
    stats = RunStats(dry_run=settings.dry_run)
    try:
        _cleanup_start(settings)
        job = _prepare_playlist(
            url,
            settings,
            playlist_items=playlist_items,
            series_folder=series_folder,
        )
        note_series(settings, job.series_name, None)
        _print_youtube_unit(job, settings)
        if settings.dry_run:
            _tally_youtube_plan(job, stats)
            return finish(settings, stats)
        _apply_youtube_job(job, settings, stats, format_selector)
        return finish(settings, stats)
    except YoutubeAuthError as exc:
        return _listing_failed(settings, stats, exc)
    except KeyboardInterrupt:
        stats.interrupted = True
        error("interrupted")
        return finish(settings, stats)


def run_youtube_manifest(
    manifest: YoutubeManifest,
    settings: Settings,
    format_selector: str | None = None,
) -> int:
    stats = RunStats(dry_run=settings.dry_run)
    try:
        _cleanup_start(settings)
        jobs: list[YoutubePlaylistJob] = []
        last_series: str | None = None
        for series in manifest.series:
            for item in series.playlists:
                job = _prepare_playlist(
                    item.url,
                    replace(settings, season=item.season),
                    series_folder=series.name,
                )
                last_series = note_series(settings, series.name, last_series)
                _print_youtube_unit(job, settings)
                jobs.append(job)
        if settings.dry_run:
            for job in jobs:
                _tally_youtube_plan(job, stats)
            return finish(settings, stats)
        for job in jobs:
            if not _apply_youtube_job(job, settings, stats, format_selector):
                return finish(settings, stats)
        return finish(settings, stats)
    except YoutubeAuthError as exc:
        return _listing_failed(settings, stats, exc)
    except KeyboardInterrupt:
        stats.interrupted = True
        error("interrupted")
        return finish(settings, stats)


def _apply_youtube_job(
    job: YoutubePlaylistJob,
    settings: Settings,
    stats: RunStats,
    format_selector: str | None = None,
) -> bool:
    series = job.series
    season_path = job.season_path
    season_number = job.season_number
    actions = job.actions
    playlist = job.playlist
    index = load_index(series)
    cache = load_cache(series)
    art = _fetch_channel_art(playlist, settings)

    series.mkdir(parents=True, exist_ok=True)
    season_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    old_dest = settings.old_dir / playlist.channel / stamp

    moved = [
        action
        for action in actions
        if action.kind in {ActionKind.REMOVE, ActionKind.REPLACE} and action.old_basename
    ]
    if moved:
        log_step(settings, f"Moving {len(moved)} replaced/removed item(s) to {old_dest}")
    for action in moved:
        assert action.old_basename is not None
        move_episode_files(season_path, action.old_basename, old_dest)

    rename_pairs = [
        (action.old_basename, action.new_basename)
        for action in actions
        if action.kind == ActionKind.RENAME and action.old_basename and action.new_basename
    ]
    if rename_pairs:
        log_step(settings, f"Renaming {len(rename_pairs)} episode(s)")
    apply_renames(season_path, rename_pairs)

    index.channel_id = playlist.channel_id
    index.channel_name = playlist.channel
    _ensure_playlist_record(index, playlist, season_number)
    record = index.playlists[playlist.playlist_id]
    for action in moved:
        record.episodes.pop(action.video_id, None)
    for action in actions:
        if action.kind != ActionKind.RENAME or action.live is None or action.new_basename is None:
            continue
        stored = record.episodes.get(action.video_id)
        if stored is None:
            continue
        stored.episode = action.live.playlist_index
        stored.title = action.live.title
        stored.basename = action.new_basename
    save_index(series, index)

    log_step(settings, "Writing series NFO files and artwork")
    _write_series_metadata(series, season_path, playlist, index, season_number, art)
    write_series_artwork(series, season_path, season_number, playlist, art)

    downloads = [
        action
        for action in actions
        if action.kind in {ActionKind.ADD, ActionKind.REPLACE} and action.live and action.new_basename
    ]
    sidecars = [
        action
        for action in actions
        if action.kind in {ActionKind.REFRESH, ActionKind.RENAME} and action.live
    ]
    staging_parent = str(settings.staging) if settings.staging else None
    if downloads:
        hint = format_size_estimate(_youtube_download_bytes(downloads))
        extra = f"  {hint}" if hint else ""
        log_step(
            settings,
            f"Downloading {len(downloads)} of {len(playlist.episodes)} episodes{extra}",
        )
        if settings.staging:
            settings.staging.mkdir(parents=True, exist_ok=True)
            log_step(settings, f"Staging downloads on local disk: {settings.staging}")
        else:
            log_step(settings, "Staging downloads in the system temp directory")
        with tempfile.TemporaryDirectory(
            prefix="yt-dlp-emby-", dir=staging_parent, ignore_cleanup_errors=True
        ) as tmp:
            work = Path(tmp)
            mark_live_staging(work)
            for i, action in enumerate(downloads, start=1):
                assert action.live is not None and action.new_basename is not None
                video_url = _video_url(action.live)
                local_stem = work / action.new_basename
                dest = season_path / action.new_basename
                already = media_exists(season_path, action.new_basename)
                existing_height = (
                    video_height(season_path / f"{action.new_basename}.mkv", settings.ffmpeg)
                    if already
                    else None
                )
                if already and action.kind == ActionKind.ADD:
                    if existing_height is not None and existing_height < TARGET_HEIGHT:
                        log_step(
                            settings,
                            f"[{i}/{len(downloads)}] Replacing {existing_height}p with up to 1080p: {action.new_basename}",
                        )
                    else:
                        log_step(
                            settings,
                            f"[{i}/{len(downloads)}] Skipping existing {action.new_basename}",
                        )
                        stats.skipped += 1
                        episode = (
                            episode_from_cache(action.live, cache[action.live.video_id])
                            if action.live.video_id in cache
                            else action.live
                        )
                        playlist = _commit_episode(
                            series, season_path, playlist, index, season_number, episode, cache
                        )
                        continue
                eta = stats.eta(len(downloads) - i)
                extra = f"  ETA {eta}" if eta else ""
                log_step(
                    settings,
                    f"[{i}/{len(downloads)}] Downloading {action.new_basename}{extra}",
                )
                started = time.monotonic()
                try:
                    info_dict = download_video(
                        video_url, local_stem, settings, format_selector=format_selector
                    )
                except YoutubeAuthError as exc:
                    error(str(exc))
                    stats.failed += 1
                    stats.failures.append((action.new_basename, str(exc)))
                    stats.remaining = len(downloads) - i
                    return False
                except Exception as exc:
                    error(f"download failed for {action.new_basename}: {exc}")
                    stats.failed += 1
                    stats.failures.append((action.new_basename, str(exc)))
                    continue
                if not info_dict.get("id"):
                    error(f"download returned no metadata for {action.new_basename}")
                    stats.failed += 1
                    stats.failures.append((action.new_basename, "download returned no metadata"))
                    continue
                log_step(settings, f"[{i}/{len(downloads)}] Copying to library")
                copy_progress = DownloadProgress(enabled=settings.show_progress)
                promote_episode(local_stem, dest, copy_progress)
                stats.mark_download(time.monotonic() - started)
                stats.downloaded += 1
                episode = _keep_listing(
                    action.live,
                    episode_from_info(info_dict, action.live.playlist_index),
                )
                playlist = _commit_episode(
                    series, season_path, playlist, index, season_number, episode, cache
                )

    for action in sidecars:
        assert action.live is not None
        episode = _resolve_episode(
            action.live,
            cache,
            settings,
            force=settings.force_refetch,
        )
        playlist = _commit_episode(
            series, season_path, playlist, index, season_number, episode, cache
        )

    _write_series_metadata(series, season_path, playlist, index, season_number, art)
    save_index(series, index)
    stats.skipped += len(sidecars)
    return True
