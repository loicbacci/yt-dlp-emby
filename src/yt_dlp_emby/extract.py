"""Extract playlist and channel metadata via yt-dlp."""

from __future__ import annotations

import json
import os
import re
import shutil
from contextlib import contextmanager
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable

from yt_dlp import YoutubeDL
from yt_dlp.utils import extract_attributes, get_elements_html_by_class

from yt_dlp_emby.auth import auth_error_from_exception
from yt_dlp_emby.cookies import sandbox_cookiefile
from yt_dlp_emby.progress import ExtractProgress, YtdlpLogger


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
    candidates: list[tuple[tuple[int, ...], Path]] = []
    for path in nvm.glob("*/bin/node"):
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        version = path.parent.parent.name.lstrip("v")
        parts: list[int] = []
        for piece in version.split("."):
            try:
                parts.append(int(piece))
            except ValueError:
                parts.append(0)
        candidates.append((tuple(parts), path))
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return str(candidates[0][1])


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


def _duration(entry: dict[str, Any]) -> float | None:
    value = entry.get("duration")
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value <= 0:
        return None
    return float(value)


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
        if entry.get("error") or entry.get("_type") == "error":
            continue
        if entry.get("id") is None:
            continue
        index += 1
        raw_index = entry.get("playlist_index")
        if isinstance(raw_index, bool) or not isinstance(raw_index, int) or raw_index < 1:
            playlist_index = index
        else:
            playlist_index = raw_index
        episodes.append(
            EpisodeInfo(
                video_id=str(entry["id"]),
                title=str(entry.get("title") or entry["id"]),
                description=str(entry.get("description") or ""),
                playlist_index=playlist_index,
                upload_date=entry.get("upload_date"),
                duration=_duration(entry),
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


@contextmanager
def _youtube_dl(opts: dict[str, Any]):
    with sandbox_cookiefile(opts.get("cookiefile")) as cookiefile:
        run_opts = dict(opts)
        if cookiefile:
            run_opts["cookiefile"] = cookiefile
        with YoutubeDL(run_opts) as ydl:
            yield ydl


def _ydl_extract(url: str, opts: dict[str, Any]) -> dict[str, Any]:
    with _youtube_dl(opts) as ydl:
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
    youtube: bool = True,
) -> dict[str, Any]:
    opts: dict[str, Any] = {
        "quiet": not verbose,
        "verbose": verbose,
        "no_warnings": False,
        "skip_download": True,
        "ignoreerrors": True,
        "socket_timeout": 30,
    }
    if youtube:
        opts["extractor_args"] = {"youtube": {"player_client": ["tv", "android", "web"]}}
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


def _run_extract(url: str, opts: dict[str, Any], fn: ExtractFn) -> dict[str, Any]:
    try:
        return fn(url, opts)
    except Exception as exc:
        auth = auth_error_from_exception(url, exc)
        if auth is not None:
            raise auth from exc
        raise


def _extract_logger(
    *,
    progress: bool,
    listing: str,
    site: str,
    verbose: bool,
    emit_warnings: bool,
) -> tuple[ExtractProgress, YtdlpLogger]:
    display = ExtractProgress(enabled=progress, heartbeat=progress, listing=listing, site=site)
    logger = YtdlpLogger(
        display,
        site=site,
        emit_warnings=emit_warnings and not verbose,
        emit_errors=not verbose,
        verbose=verbose,
    )
    return display, logger


def extract_playlist(
    url: str,
    *,
    playlist_items: str | None = None,
    cookies_from_browser: str | None = None,
    cookiefile: str | None = None,
    extract_fn: ExtractFn | None = None,
    progress: bool = False,
    verbose: bool = False,
    emit_warnings: bool = True,
) -> PlaylistInfo:
    from yt_dlp_emby.server.series_discover import assert_public_catalog_url

    assert_public_catalog_url(
        url, require_catalog_host=extract_fn is None
    )  # accepted risk: single-resolution + redirect guard, no IP pinning
    display, logger = _extract_logger(
        progress=progress,
        listing="playlist",
        site="YouTube",
        verbose=verbose,
        emit_warnings=emit_warnings,
    )
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
        info = _run_extract(url, opts, fn)
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
    emit_warnings: bool = True,
) -> EpisodeInfo:
    _display, logger = _extract_logger(
        progress=False,
        listing="playlist",
        site="YouTube",
        verbose=verbose,
        emit_warnings=emit_warnings,
    )
    opts = _base_opts(
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookiefile,
        verbose=verbose,
        logger=logger,
    )
    fn = extract_fn or _ydl_extract
    info = _run_extract(url, opts, fn)
    return episode_from_info(info, playlist_index)


def extract_channel_art(
    channel_id: str,
    *,
    cookies_from_browser: str | None = None,
    cookiefile: str | None = None,
    extract_fn: ExtractFn | None = None,
    progress: bool = False,
    verbose: bool = False,
    emit_warnings: bool = True,
) -> ChannelArt:
    display, logger = _extract_logger(
        progress=progress,
        listing="channel",
        site="YouTube",
        verbose=verbose,
        emit_warnings=emit_warnings,
    )
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
        info = _run_extract(url, opts, fn)
    finally:
        if progress:
            display.finish("Channel artwork complete")
    return parse_channel_art(info)


@dataclass(frozen=True)
class DropoutListing:
    url: str
    title: str
    dropout_episode: int
    duration: float | None = None
    filesize: int | None = None


def _entry_url(entry: dict[str, Any]) -> str | None:
    url = entry.get("url") or entry.get("webpage_url")
    if url and str(url).startswith("http"):
        return str(url)
    return _webpage_url(entry)


def _title_from_url(url: str) -> str:
    slug = url.rstrip("/").rsplit("/", 1)[-1]
    return slug.replace("-", " ").strip() or slug


def _url_slug(url: str) -> str:
    return url.rstrip("/").rsplit("/", 1)[-1].split("?")[0]


def parse_dropout_browse_titles(webpage: str) -> dict[str, str]:
    """Map episode URLs to on-site titles from a Dropout season grid page."""
    titles: dict[str, str] = {}
    for html in get_elements_html_by_class("browse-item-link", webpage) or []:
        attrs = extract_attributes(html)
        href = attrs.get("href")
        if not href:
            continue
        title = ""
        props = attrs.get("data-track-event-properties")
        if props:
            try:
                payload = json.loads(props)
            except json.JSONDecodeError:
                payload = {}
            label = payload.get("label")
            if isinstance(label, str):
                title = label.strip()
        if not title:
            alt = re.search(r'<img\b[^>]*\balt="([^"]*)"', html, flags=re.I)
            if alt:
                title = alt.group(1).strip()
        if title:
            titles[href] = title
    return titles


def _lookup_browse_title(episode_url: str, page_titles: dict[str, str]) -> str:
    if episode_url in page_titles:
        return page_titles[episode_url]
    slug = _url_slug(episode_url)
    for href, title in page_titles.items():
        if _url_slug(href) == slug:
            return title
    return ""


def _ydl_webpage(url: str, opts: dict[str, Any]) -> str:
    with _youtube_dl(opts) as ydl:
        return ydl.urlopen(url).read().decode("utf-8", "replace")


def _load_dropout_season_titles(season_url: str, opts: dict[str, Any]) -> dict[str, str]:
    titles: dict[str, str] = {}
    page_size = 24
    for page in range(1, 51):
        page_url = f"{season_url}?page={page}"
        try:
            webpage = _ydl_webpage(page_url, opts)
        except Exception as exc:
            from yt_dlp_emby.auth import auth_error_from_exception

            auth = auth_error_from_exception(page_url, exc)
            if auth is not None:
                raise auth from exc
            break
        batch = parse_dropout_browse_titles(webpage)
        if not batch:
            break
        titles.update(batch)
        if len(batch) < page_size:
            break
    return titles


def extract_dropout_season(
    url: str,
    *,
    cookies_from_browser: str | None = None,
    cookiefile: str | None = None,
    extract_fn: ExtractFn | None = None,
    progress: bool = False,
    verbose: bool = False,
    emit_warnings: bool = True,
) -> list[DropoutListing]:
    from yt_dlp_emby.server.series_discover import assert_public_catalog_url

    assert_public_catalog_url(
        url, require_catalog_host=extract_fn is None
    )  # accepted risk: single-resolution + redirect guard, no IP pinning
    display, logger = _extract_logger(
        progress=progress,
        listing="season",
        site="Dropout",
        verbose=verbose,
        emit_warnings=emit_warnings,
    )
    opts = _base_opts(
        cookies_from_browser=cookies_from_browser,
        cookiefile=cookiefile,
        logger=logger,
        verbose=verbose,
        youtube=False,
    )
    opts["extract_flat"] = "in_playlist"
    if progress:
        display.status("Connecting to Dropout…")
    fn = extract_fn or _ydl_extract
    page_titles: dict[str, str] = {}
    try:
        info = _run_extract(url, opts, fn)
        entries = info.get("entries") or []
        if info.get("_type") == "video" or not entries:
            entries = [info]
        missing_titles = any(
            not str(entry.get("title") or entry.get("episode") or "").strip()
            for entry in entries
            if entry
        )
        if missing_titles and extract_fn is None:
            if progress:
                display.status("Reading episode titles…")
            page_titles = _load_dropout_season_titles(url, opts)
    finally:
        if progress:
            display.finish("Season listing complete")
    listed: list[DropoutListing] = []
    index = 0
    for entry in entries:
        if not entry:
            continue
        if entry.get("error") or entry.get("_type") == "error":
            continue
        episode_url = _entry_url(entry)
        if not episode_url:
            continue
        index += 1
        episode_number = entry.get("episode_number")
        if isinstance(episode_number, bool):
            dropout_episode = index
        else:
            try:
                dropout_episode = int(episode_number) if episode_number is not None else index
            except (TypeError, ValueError):
                dropout_episode = index
        if dropout_episode < 1:
            dropout_episode = index
        title = (
            str(entry.get("title") or entry.get("episode") or "").strip()
            or _lookup_browse_title(episode_url, page_titles)
            or _title_from_url(episode_url)
        )
        listed.append(
            DropoutListing(
                url=episode_url,
                title=title,
                dropout_episode=dropout_episode,
                duration=_duration(entry),
                filesize=_filesize(entry),
            )
        )
    return listed
