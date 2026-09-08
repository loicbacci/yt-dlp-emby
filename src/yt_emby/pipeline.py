"""Orchestrate extract, sync, download, NFO, and artwork."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from yt_emby.config import Settings
from yt_emby.download import download_video
from yt_emby.extract import (
    ChannelArt,
    EpisodeInfo,
    PlaylistInfo,
    extract_channel_art,
    extract_playlist,
)
from yt_emby.images import download_image
from yt_emby.library import (
    EpisodeRecord,
    LibraryIndex,
    PlaylistRecord,
    assign_season,
    episode_stem,
    load_index,
    save_index,
    season_dir,
    series_dir,
)
from yt_emby.nfo import write_episode_nfo, write_season_nfo, write_tvshow_nfo
from yt_emby.sync import (
    ActionKind,
    SyncAction,
    apply_renames,
    move_episode_files,
    plan_sync,
)


def _premiered(playlist: PlaylistInfo) -> str | None:
    dates = [ep.upload_date for ep in playlist.episodes if ep.upload_date]
    if not dates:
        return None
    oldest = min(dates)
    return f"{oldest[:4]}-{oldest[4:6]}-{oldest[6:]}"


def write_artwork(
    series: Path,
    season: Path,
    season_number: int,
    playlist: PlaylistInfo,
    art: ChannelArt | None,
    episodes: list[tuple[str, EpisodeInfo]],
) -> None:
    if art and art.avatar_url:
        download_image(art.avatar_url, series / "poster.jpg")
    if art and art.banner_url:
        download_image(art.banner_url, series / "fanart.jpg")
    if playlist.thumbnail_url:
        download_image(playlist.thumbnail_url, series / f"season{season_number:02d}-poster.jpg")
        download_image(playlist.thumbnail_url, season / "poster.jpg")
    for stem, episode in episodes:
        if episode.thumbnail_url:
            download_image(episode.thumbnail_url, season / f"{stem}-thumb.jpg")


def _write_metadata(
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
    for episode in playlist.episodes:
        stem = episode_stem(playlist.channel, season_number, episode.playlist_index, episode.title)
        write_episode_nfo(
            season_path / f"{stem}.nfo",
            episode=episode,
            season=season_number,
            episode_number=episode.playlist_index,
        )


def _record_from_live(playlist: PlaylistInfo, season: int) -> PlaylistRecord:
    episodes = {
        ep.video_id: EpisodeRecord(
            video_id=ep.video_id,
            episode=ep.playlist_index,
            title=ep.title,
            basename=episode_stem(playlist.channel, season, ep.playlist_index, ep.title),
            duration=ep.duration,
            filesize=ep.filesize,
            upload_date=ep.upload_date,
        )
        for ep in playlist.episodes
    }
    return PlaylistRecord(
        playlist_id=playlist.playlist_id,
        season=season,
        title=playlist.title,
        description=playlist.description,
        episodes=episodes,
    )


def _print_plan(actions: list[SyncAction]) -> None:
    if not actions:
        print("nothing to do")
        return
    for action in actions:
        target = action.new_basename or action.old_basename or action.video_id
        print(f"{action.kind.value}: {target}")


def run_download(
    url: str,
    settings: Settings,
    format_selector: str | None = None,
    *,
    playlist_items: str | None = None,
) -> int:
    playlist = extract_playlist(
        url,
        playlist_items=playlist_items,
        cookies_from_browser=settings.cookies_from_browser,
    )
    art: ChannelArt | None = None
    if playlist.channel_id:
        try:
            art = extract_channel_art(
                playlist.channel_id,
                cookies_from_browser=settings.cookies_from_browser,
            )
        except Exception as exc:  # noqa: BLE001 — channel art is optional
            print(f"warning: could not fetch channel artwork: {exc}")

    series = series_dir(settings.library, playlist.channel)
    index = load_index(series)
    if not index.channel_id:
        index.channel_id = playlist.channel_id
        index.channel_name = playlist.channel
    season_number = assign_season(index, playlist.playlist_id, settings.season)
    existing = index.playlists.get(playlist.playlist_id)
    actions = plan_sync(playlist, existing, season_number)
    season_path = season_dir(series, season_number)

    print(f"series={series}")
    print(f"season={season_number} ({playlist.title})")
    _print_plan(actions)

    if settings.dry_run:
        return 0

    series.mkdir(parents=True, exist_ok=True)
    season_path.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
    old_dest = settings.old_dir / playlist.channel / stamp

    for action in actions:
        if action.kind in {ActionKind.REMOVE, ActionKind.REPLACE} and action.old_basename:
            move_episode_files(season_path, action.old_basename, old_dest)

    apply_renames(
        season_path,
        [
            (action.old_basename, action.new_basename)
            for action in actions
            if action.kind == ActionKind.RENAME and action.old_basename and action.new_basename
        ],
    )

    index.channel_id = playlist.channel_id
    index.channel_name = playlist.channel
    index.playlists[playlist.playlist_id] = _record_from_live(playlist, season_number)

    _write_metadata(series, season_path, playlist, index, season_number, art)
    write_artwork(
        series,
        season_path,
        season_number,
        playlist,
        art,
        [
            (
                episode_stem(playlist.channel, season_number, ep.playlist_index, ep.title),
                ep,
            )
            for ep in playlist.episodes
        ],
    )

    for action in actions:
        if action.kind not in {ActionKind.ADD, ActionKind.REPLACE}:
            continue
        if not action.live or not action.new_basename:
            continue
        video_url = action.live.webpage_url or f"https://www.youtube.com/watch?v={action.video_id}"
        dest = season_path / action.new_basename
        print(f"downloading {action.new_basename}")
        download_video(video_url, dest, settings, format_selector=format_selector)

    save_index(series, index)
    return 0
