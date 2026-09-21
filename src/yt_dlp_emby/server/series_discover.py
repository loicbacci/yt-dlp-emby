"""Discover catalog sources for the series API."""

from __future__ import annotations

import ipaddress
import re
import socket
from typing import Any, Callable
from urllib.parse import urlparse

from yt_dlp import YoutubeDL

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.dropout import resolve_emby_target
from yt_dlp_emby.dropout_manifest import DropoutSeason
from yt_dlp_emby.dropout_seasons import discover_dropout_seasons
from yt_dlp_emby.extract import _base_opts
from yt_dlp_emby.images import _ip_is_blocked

FetchHtml = Callable[[str], str]

_CATALOG_HOSTS = {
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
    "music.youtube.com",
    "dropout.tv",
    "www.dropout.tv",
    "watch.dropout.tv",
    "vhx.tv",
    "embed.vhx.tv",
    "api.vhx.tv",
}


def _host_is_catalog(host: str) -> bool:
    lowered = host.lower().rstrip(".")
    if lowered in _CATALOG_HOSTS:
        return True
    return any(lowered.endswith("." + item) for item in _CATALOG_HOSTS)


def assert_public_catalog_url(url: str, *, require_catalog_host: bool = True) -> None:
    """Reject non-http(s), private IPs, and (by default) non-catalog hosts."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ConfigError("URL must be http or https")
    host = parsed.hostname
    if not host:
        raise ConfigError("URL is missing a host")
    if require_catalog_host and not _host_is_catalog(host):
        raise ConfigError(f"unsupported catalog host: {host}")
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        ip = None
    if ip is not None and _ip_is_blocked(ip):
        raise ConfigError("URL points to a private or reserved address")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return
    for info in infos:
        raw = info[4][0]
        try:
            resolved = ipaddress.ip_address(raw)
        except ValueError:
            continue
        if _ip_is_blocked(resolved):
            raise ConfigError("URL resolves to a private or reserved address")


class ChannelDiscoverError(Exception):
    def __init__(self, url: str, message: str) -> None:
        super().__init__(message)
        self.url = url
        self.message = message


_FS_PATH_RE = re.compile(r"(?<![\w:/])(?:/[A-Za-z0-9_.-]+)+/?")
_HOME_RE = re.compile(r"~(?:/[A-Za-z0-9_.-]+)*/?")


def sanitize_discovery_message(text: str, *, limit: int = 300) -> str:
    """Scrub absolute paths from yt-dlp errors and truncate for API responses."""
    scrubbed = _FS_PATH_RE.sub("<path>", str(text))
    scrubbed = _HOME_RE.sub("<path>", scrubbed)
    scrubbed = " ".join(scrubbed.split())
    if len(scrubbed) > limit:
        return scrubbed[: max(0, limit - 1)].rstrip() + "…"
    return scrubbed or "discovery failed"


def _ydl_urlopen(url: str, *, cookiefile: str | None) -> str:
    # Accepted risk: single-resolution + redirect guard, no IP pinning.
    assert_public_catalog_url(url)
    opts = _base_opts(cookiefile=cookiefile, verbose=False)
    with YoutubeDL(opts) as ydl:
        return ydl.urlopen(url).read().decode("utf-8", "replace")


def discover_dropout_source(
    url: str,
    *,
    cookiefile: str | None,
    fetch_html: FetchHtml | None = None,
) -> list[dict[str, Any]]:
    # Accepted risk: single-resolution + redirect guard, no IP pinning.
    assert_public_catalog_url(url)
    fetch = fetch_html or (lambda target: _ydl_urlopen(target, cookiefile=cookiefile))
    raw = discover_dropout_seasons(url, fetch_html=fetch)
    seasons: list[dict[str, Any]] = []
    for item in raw:
        dropout = int(str(item["dropout"]))
        seasons.append(
            {
                "dropout": dropout,
                "url": str(item["url"]),
                "to_season": int(str(item.get("to_season", dropout))),
                "enabled": bool(item.get("enabled", True)),
                "only_episodes": [],
                "remaps": [],
            }
        )
    return seasons


def _is_youtube_playlist_url(url: str) -> bool:
    lowered = url.casefold()
    return "list=" in lowered or "/playlist" in lowered


def _is_youtube_channel_url(url: str) -> bool:
    lowered = url.casefold()
    return any(token in lowered for token in ("/channel/", "/c/", "/user/", "/@", "/playlists"))


def _playlist_url_from_entry(entry: dict[str, Any] | None) -> str | None:
    if not entry:
        return None
    url = str(entry.get("url") or entry.get("webpage_url") or "").strip()
    if not url:
        return None
    kind = str(entry.get("_type") or "")
    ie_key = str(entry.get("ie_key") or "")
    if kind == "playlist" or "playlist" in ie_key.casefold():
        return url
    if _is_youtube_playlist_url(url):
        return url
    return None


def discover_youtube_sources(
    url: str,
    *,
    cookiefile: str | None,
    extract_channel=None,
) -> list[dict[str, Any]]:
    """Return source dicts with url + seasons (one season per playlist)."""
    text = url.strip()
    if not text:
        return []
    # Accepted risk: single-resolution + redirect guard, no IP pinning.
    assert_public_catalog_url(text)
    if _is_youtube_playlist_url(text) and not _is_youtube_channel_url(text):
        return [_youtube_playlist_source(text, season_number=1)]
    if not _is_youtube_channel_url(text):
        return [_youtube_playlist_source(text, season_number=1)]
    try:
        if extract_channel is not None:
            info = extract_channel(text)
        else:
            opts = _base_opts(cookiefile=cookiefile, verbose=False)
            opts["extract_flat"] = "in_playlist"
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(text, download=False)
    except Exception as exc:
        raise ChannelDiscoverError(
            text, sanitize_discovery_message(str(exc) or "channel extract failed")
        ) from exc
    entries = (info or {}).get("entries") or []
    sources: list[dict[str, Any]] = []
    for entry in entries:
        pl_url = _playlist_url_from_entry(entry)
        if not pl_url:
            continue
        title = entry.get("title") if isinstance(entry, dict) else None
        sources.append(
            _youtube_playlist_source(
                pl_url,
                season_number=len(sources) + 1,
                label=str(title) if title else "",
            )
        )
    if sources:
        return sources
    return [_youtube_playlist_source(text, season_number=1)]


def _youtube_playlist_source(
    url: str,
    *,
    season_number: int,
    label: str | None = None,
) -> dict[str, Any]:
    sublabel = label or ""
    return {
        "url": url,
        "error": None,
        "seasons": [
            {
                "dropout": None,
                "url": url,
                "to_season": season_number,
                "enabled": True,
                "only_episodes": [],
                "remaps": [],
                "skip_ids": [],
                "label": f"Season {season_number}" if season_number else "Season",
                "sublabel": sublabel,
            }
        ],
    }


def merge_dropout_seasons(
    old: tuple[DropoutSeason, ...],
    discovered: list[dict[str, Any]],
) -> tuple[DropoutSeason, ...]:
    by_dropout = {se.dropout: se for se in old if se.dropout is not None}
    merged: list[DropoutSeason] = []
    for raw in discovered:
        dropout = int(raw["dropout"])
        prev = by_dropout.get(dropout)
        merged.append(
            DropoutSeason(
                dropout=dropout,
                url=str(raw["url"]),
                to_season=int(raw.get("to_season", dropout)),
                remap=prev.remap if prev else (),
                only_episodes=prev.only_episodes if prev else None,
                enabled=prev.enabled if prev else bool(raw.get("enabled", True)),
            )
        )
    return tuple(merged)


def library_episode_status(
    skipped: bool,
    mapped_season: int | None,
    mapped_episode: int | None,
    on_disk: set[tuple[int, int]] | None = None,
) -> str:
    if skipped:
        return "skipped"
    if mapped_season is None or mapped_episode is None:
        return "unmapped"
    if on_disk is not None and (mapped_season, mapped_episode) in on_disk:
        return "downloaded"
    return "missing"


def dropout_episode_rows(
    season: DropoutSeason,
    listings: list[Any],
    *,
    on_disk: set[tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    allowed = set(season.only_episodes) if season.only_episodes else None
    rows: list[dict[str, Any]] = []
    for listing in listings:
        dep = int(listing.dropout_episode)
        skipped = False
        mapped_season: int | None = None
        mapped_episode: int | None = None
        mapped_title: str | None = None
        if allowed is not None and dep not in allowed:
            skipped = True
        target = resolve_emby_target(listing, season)
        if target == "skip":
            skipped = True
        elif isinstance(target, tuple):
            mapped_season, mapped_episode, mapped_title = target
        rows.append(
            {
                "id": str(dep),
                "title": listing.title,
                "url": listing.url,
                "source_episode": dep,
                "skipped": skipped,
                "mapped_season": mapped_season,
                "mapped_episode": mapped_episode,
                "mapped_title": mapped_title,
                "status": library_episode_status(skipped, mapped_season, mapped_episode, on_disk),
            }
        )
    return rows


def youtube_episode_rows(
    season: dict[str, Any],
    playlist,
    *,
    on_disk: set[tuple[int, int]] | None = None,
) -> list[dict[str, Any]]:
    skip_ids = {str(x) for x in (season.get("skip_ids") or [])}
    to_season = season.get("to_season") or 1
    rows: list[dict[str, Any]] = []
    for episode in playlist.episodes:
        vid = episode.video_id
        skipped = vid in skip_ids
        mapped_season = None if skipped else to_season
        mapped_episode = None if skipped else episode.playlist_index
        rows.append(
            {
                "id": vid,
                "title": episode.title,
                "url": episode.webpage_url or f"https://www.youtube.com/watch?v={vid}",
                "source_episode": episode.playlist_index,
                "skipped": skipped,
                "mapped_season": mapped_season,
                "mapped_episode": mapped_episode,
                "mapped_title": episode.title,
                "status": library_episode_status(skipped, mapped_season, mapped_episode, on_disk),
            }
        )
    return rows
