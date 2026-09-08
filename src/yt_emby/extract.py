"""Extract playlist and channel metadata via yt-dlp."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from yt_dlp import YoutubeDL

from yt_emby.progress import ExtractProgress, YtdlpLogger


@dataclass(frozen=True)
class EpisodeInfo:
    video_id: str
    title: str
    description: str
    playlist_index: int
    upload_date: str | None = None
    duration: float | None = None
    filesize: int | None = None
    thumbnail_url: str | None = None
    webpage_url: str | None = None


@dataclass(frozen=True)
class PlaylistInfo:
    playlist_id: str
    title: str
    description: str
    channel: str
    channel_id: str
    thumbnail_url: str | None
    episodes: list[EpisodeInfo]
    webpage_url: str | None = None


@dataclass(frozen=True)
class ChannelArt:
    channel_id: str
    channel: str
    description: str
    avatar_url: str | None
    banner_url: str | None


ExtractFn = Callable[[str, dict[str, Any]], dict[str, Any]]


def find_node() -> str | None:
    found = shutil.which("node")
    if found:
        return found
    nvm = Path.home() / ".nvm" / "versions" / "node"
    if not nvm.is_dir():
        return None
    for path in sorted(nvm.glob("*/bin/node"), reverse=True):
        if path.is_file() and os.access(path, os.X_OK):
            return str(path)
    return None


def js_runtime_opts() -> dict[str, Any]:
    node = find_node()
    if not node:
        return {}
    return {"js_runtimes": {"node": {"path": node}}}


def pick_best_thumbnail(thumbnails: list[dict[str, Any]] | None) -> str | None:
    if not thumbnails:
        return None
    ranked = sorted(
        (t for t in thumbnails if t.get("url")),
        key=lambda t: (t.get("width") or 0, t.get("height") or 0, t.get("preference") or 0),
    )
    if not ranked:
        return None
    return str(ranked[-1]["url"])


def pick_avatar(thumbnails: list[dict[str, Any]] | None) -> str | None:
    if not thumbnails:
        return None
    for thumb in thumbnails:
        if thumb.get("id") == "avatar_uncropped" and thumb.get("url"):
            return str(thumb["url"])
    avatars = [t for t in thumbnails if (t.get("preference") or 0) >= 0 and t.get("url")]
    if avatars:
        return pick_best_thumbnail(avatars)
    return pick_best_thumbnail(thumbnails)


def pick_banner(thumbnails: list[dict[str, Any]] | None) -> str | None:
    if not thumbnails:
        return None
    for thumb in thumbnails:
        if thumb.get("id") == "banner_uncropped" and thumb.get("url"):
            return str(thumb["url"])
    banners = [
        t
        for t in thumbnails
        if t.get("id") != "avatar_uncropped" and (t.get("preference") or 0) < 0 and t.get("url")
    ]
    if not banners:
        return None
    return pick_best_thumbnail(banners)


def _episode_thumbnail(entry: dict[str, Any]) -> str | None:
    if entry.get("thumbnail"):
        return str(entry["thumbnail"])
    return pick_best_thumbnail(entry.get("thumbnails"))


def _filesize(entry: dict[str, Any]) -> int | None:
    for key in ("filesize", "filesize_approx"):
        value = entry.get(key)
        if isinstance(value, (int, float)):
            return int(value)
    return None


def _webpage_url(entry: dict[str, Any]) -> str | None:
    url = entry.get("webpage_url") or entry.get("url")
    if url and str(url).startswith("http"):
        return str(url)
    video_id = entry.get("id")
    if video_id:
        return f"https://www.youtube.com/watch?v={video_id}"
    return None


def parse_playlist(info: dict[str, Any]) -> PlaylistInfo:
    entries = info.get("entries") or []
    episodes: list[EpisodeInfo] = []
    index = 0
    for entry in entries:
        if not entry:
            continue
        if entry.get("id") is None:
            continue
        index += 1
        playlist_index = entry.get("playlist_index") or index
        episodes.append(
            EpisodeInfo(
                video_id=str(entry["id"]),
                title=str(entry.get("title") or entry["id"]),
                description=str(entry.get("description") or ""),
                playlist_index=int(playlist_index),
                upload_date=entry.get("upload_date"),
                duration=float(entry["duration"]) if entry.get("duration") is not None else None,
                filesize=_filesize(entry),
                thumbnail_url=_episode_thumbnail(entry),
                webpage_url=_webpage_url(entry),
            )
        )
    channel = str(info.get("channel") or info.get("uploader") or "Unknown Channel")
    channel_id = str(info.get("channel_id") or info.get("uploader_id") or "")
    return PlaylistInfo(
        playlist_id=str(info.get("id") or ""),
        title=str(info.get("title") or info.get("id") or "Playlist"),
        description=str(info.get("description") or ""),
        channel=channel,
        channel_id=channel_id,
        thumbnail_url=pick_best_thumbnail(info.get("thumbnails")),
        episodes=episodes,
        webpage_url=info.get("webpage_url") or info.get("original_url"),
    )


def episode_from_info(info: dict[str, Any], playlist_index: int) -> EpisodeInfo:
    entry = info
    if info.get("_type") == "playlist" and info.get("entries"):
        entry = next((item for item in info["entries"] if item and item.get("id")), info)
    parsed = parse_playlist({**info, "entries": [entry]})
    if not parsed.episodes:
        raise ValueError("No video metadata returned")
    return replace(parsed.episodes[0], playlist_index=playlist_index)


def with_episode(playlist: PlaylistInfo, episode: EpisodeInfo) -> PlaylistInfo:
    return replace(
        playlist,
        episodes=[
            episode if existing.video_id == episode.video_id else existing
            for existing in playlist.episodes
        ],
    )


def parse_channel_art(info: dict[str, Any]) -> ChannelArt:
    thumbs = info.get("thumbnails") or []
    channel_id = str(info.get("channel_id") or info.get("id") or "")
    channel = str(info.get("channel") or info.get("uploader") or info.get("title") or channel_id)
    return ChannelArt(
        channel_id=channel_id,
        channel=channel,
        description=str(info.get("description") or info.get("channel_description") or ""),
        avatar_url=pick_avatar(thumbs),
        banner_url=pick_banner(thumbs),
    )


def _ydl_extract(url: str, opts: dict[str, Any]) -> dict[str, Any]:
    with YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if not info:
        raise ValueError(f"No metadata returned for {url}")
    return info


def _base_opts(
    *,
    cookies_from_browser: str | None = None,
    cookiefile: str | None = None,
    playlist_items: str | None = None,
    logger: Any | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": not verbose,
        "verbose": verbose,
        "no_warnings": not verbose,
        "skip_download": True,
        "ignoreerrors": True,
        "extractor_args": {"youtube": {"player_client": ["tv", "android", "web"]}},
    }
    if playlist_items:
        opts["playlist_items"] = playlist_items
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    if cookiefile:
        opts["cookiefile"] = cookiefile
    if logger is not None:
        opts["logger"] = logger
    opts.update(js_runtime_opts())
    return opts


def extract_playlist(
    url: str,
    *,
    playlist_items: str | None = None,
    cookies_from_browser: str | None = None,
    cookiefile: str | None = None,
    extract_fn: ExtractFn | None = None,
    progress: bool = False,
    verbose: bool = False,
) -> PlaylistInfo:
    display = ExtractProgress(enabled=progress, heartbeat=progress)
    logger = YtdlpLogger(display) if progress else None
    opts = _base_opts(
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookiefile,
        playlist_items=playlist_items,
        logger=logger,
        verbose=verbose,
    )
    opts["extract_flat"] = "in_playlist"
    if progress:
        display.status("Connecting to YouTube…")
    fn = extract_fn or _ydl_extract
    try:
        info = fn(url, opts)
    finally:
        if progress:
            display.finish("Playlist listing complete")
    if info.get("_type") == "video" or not info.get("entries"):
        # Single video: wrap as a one-episode playlist.
        if not info.get("entries"):
            info = {
                **info,
                "id": info.get("playlist_id") or info.get("id"),
                "title": info.get("playlist_title") or info.get("title"),
                "entries": [info],
            }
    return parse_playlist(info)


def extract_video(
    url: str,
    playlist_index: int,
    *,
    cookies_from_browser: str | None = None,
    cookiefile: str | None = None,
    extract_fn: ExtractFn | None = None,
    verbose: bool = False,
) -> EpisodeInfo:
    opts = _base_opts(
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookiefile,
        verbose=verbose,
    )
    fn = extract_fn or _ydl_extract
    info = fn(url, opts)
    return episode_from_info(info, playlist_index)


def extract_channel_art(
    channel_id: str,
    *,
    cookies_from_browser: str | None = None,
    cookiefile: str | None = None,
    extract_fn: ExtractFn | None = None,
    progress: bool = False,
    verbose: bool = False,
) -> ChannelArt:
    display = ExtractProgress(enabled=progress, heartbeat=progress)
    logger = YtdlpLogger(display) if progress else None
    url = f"https://www.youtube.com/channel/{channel_id}"
    opts = _base_opts(
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookiefile,
        playlist_items="0",
        logger=logger,
        verbose=verbose,
    )
    if progress:
        display.status("Fetching channel artwork…")
    fn = extract_fn or _ydl_extract
    try:
        info = fn(url, opts)
    finally:
        if progress:
            display.finish("Channel artwork complete")
    return parse_channel_art(info)
