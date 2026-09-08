"""On-disk cache of per-video yt-dlp metadata."""

from __future__ import annotations

import json
from pathlib import Path

from yt_emby.extract import EpisodeInfo, PlaylistInfo

CACHE_FILENAME = ".yt-emby-cache.json"


def load_cache(series: Path) -> dict[str, dict]:
    path = series / CACHE_FILENAME
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    videos = data.get("videos") if isinstance(data, dict) else None
    if isinstance(videos, dict):
        return {str(key): value for key, value in videos.items() if isinstance(value, dict)}
    return {}


def save_cache(series: Path, cache: dict[str, dict]) -> None:
    series.mkdir(parents=True, exist_ok=True)
    payload = {"videos": cache}
    (series / CACHE_FILENAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def episode_to_cache(episode: EpisodeInfo) -> dict:
    return {
        "title": episode.title,
        "description": episode.description,
        "upload_date": episode.upload_date,
        "duration": episode.duration,
        "filesize": episode.filesize,
        "thumbnail_url": episode.thumbnail_url,
        "webpage_url": episode.webpage_url,
    }


def episode_from_cache(listing: EpisodeInfo, cached: dict) -> EpisodeInfo:
    duration = cached.get("duration")
    filesize = cached.get("filesize")
    return EpisodeInfo(
        video_id=listing.video_id,
        title=listing.title,
        description=str(cached.get("description") or listing.description),
        playlist_index=listing.playlist_index,
        upload_date=cached.get("upload_date") or listing.upload_date,
        duration=float(duration) if duration is not None else listing.duration,
        filesize=int(filesize) if filesize is not None else listing.filesize,
        thumbnail_url=cached.get("thumbnail_url") or listing.thumbnail_url,
        webpage_url=cached.get("webpage_url") or listing.webpage_url,
    )


def hydrate_playlist(
    playlist: PlaylistInfo,
    cache: dict[str, dict],
    *,
    force_refetch: bool,
) -> PlaylistInfo:
    if force_refetch:
        return playlist
    episodes = []
    for listing in playlist.episodes:
        cached = cache.get(listing.video_id)
        episodes.append(episode_from_cache(listing, cached) if cached else listing)
    return PlaylistInfo(
        playlist_id=playlist.playlist_id,
        title=playlist.title,
        description=playlist.description,
        channel=playlist.channel,
        channel_id=playlist.channel_id,
        thumbnail_url=playlist.thumbnail_url,
        episodes=episodes,
        webpage_url=playlist.webpage_url,
    )
