"""Extract playlist and channel metadata via yt-dlp."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from yt_dlp import YoutubeDL


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
                webpage_url=entry.get("webpage_url"),
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
    playlist_items: str | None = None,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
    }
    if playlist_items:
        opts["playlist_items"] = playlist_items
    if cookies_from_browser:
        opts["cookiesfrombrowser"] = (cookies_from_browser,)
    return opts


def extract_playlist(
    url: str,
    *,
    playlist_items: str | None = None,
    cookies_from_browser: str | None = None,
    extract_fn: ExtractFn | None = None,
) -> PlaylistInfo:
    opts = _base_opts(cookies_from_browser=cookies_from_browser, playlist_items=playlist_items)
    fn = extract_fn or _ydl_extract
    info = fn(url, opts)
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


def extract_channel_art(
    channel_id: str,
    *,
    cookies_from_browser: str | None = None,
    extract_fn: ExtractFn | None = None,
) -> ChannelArt:
    url = f"https://www.youtube.com/channel/{channel_id}"
    opts = _base_opts(cookies_from_browser=cookies_from_browser, playlist_items="0")
    fn = extract_fn or _ydl_extract
    info = fn(url, opts)
    return parse_channel_art(info)
