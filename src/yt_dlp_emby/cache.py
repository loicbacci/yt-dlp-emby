"""On-disk cache of per-video yt-dlp metadata."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from yt_dlp_emby.extract import DropoutListing, EpisodeInfo, PlaylistInfo

CACHE_FILENAME = ".yt-emby-cache.json"
DROPOUT_CACHE_DIRNAME = "cache"
DROPOUT_CACHE_FILENAME = "dropout.json"
LEGACY_DROPOUT_CACHE_FILENAME = ".yt-emby-dropout.json"


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


def dropout_cache_path(manifest_path: Path | None = None, *, cwd: Path | None = None) -> Path:
    """Listing cache next to the manifest, not on the library share."""
    root = manifest_path.parent if manifest_path is not None else (cwd or Path.cwd())
    return root / DROPOUT_CACHE_DIRNAME / DROPOUT_CACHE_FILENAME


def migrate_dropout_season_cache(dest: Path, library: Path) -> Path | None:
    """Move `{library}/.yt-emby-dropout.json` next to the manifest.

    If `dest` already exists, the leftover library file is removed and `dest` is kept.
    Returns the legacy path when it was present.
    """
    legacy = library / LEGACY_DROPOUT_CACHE_FILENAME
    if not legacy.is_file():
        return None
    if not dest.is_file():
        dest.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.move(str(legacy), dest)
        except OSError:
            dest.write_bytes(legacy.read_bytes())
            legacy.unlink()
        return legacy
    try:
        legacy.unlink()
    except OSError:
        pass
    return legacy


def load_dropout_season_cache(path: Path) -> dict[str, list[dict]]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    seasons = data.get("seasons") if isinstance(data, dict) else None
    if not isinstance(seasons, dict):
        return {}
    result: dict[str, list[dict]] = {}
    for key, value in seasons.items():
        if isinstance(value, list):
            result[str(key)] = [item for item in value if isinstance(item, dict)]
    return result


def save_dropout_season_cache(path: Path, seasons: dict[str, list[dict]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"seasons": seasons}
    path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def dropout_listings_to_cache(listings: list[DropoutListing]) -> list[dict]:
    payload: list[dict] = []
    for item in listings:
        row: dict = {
            "url": item.url,
            "title": item.title,
            "dropout_episode": item.dropout_episode,
        }
        if item.duration is not None:
            row["duration"] = item.duration
        if item.filesize is not None:
            row["filesize"] = item.filesize
        payload.append(row)
    return payload


def dropout_listings_from_cache(raw: list[dict] | None) -> list[DropoutListing] | None:
    if not raw:
        return None
    listed: list[DropoutListing] = []
    for item in raw:
        url = item.get("url")
        title = item.get("title")
        episode = item.get("dropout_episode")
        if not isinstance(url, str) or not url.startswith("http"):
            continue
        if not isinstance(title, str) or not title.strip():
            continue
        if isinstance(episode, bool) or not isinstance(episode, int):
            continue
        duration = item.get("duration")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)) or duration <= 0:
            duration = None
        else:
            duration = float(duration)
        filesize = item.get("filesize")
        if isinstance(filesize, bool) or not isinstance(filesize, int) or filesize <= 0:
            filesize = None
        listed.append(
            DropoutListing(
                url=url,
                title=title.strip(),
                dropout_episode=episode,
                duration=duration,
                filesize=filesize,
            )
        )
    return listed or None
