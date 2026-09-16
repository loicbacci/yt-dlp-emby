"""Discover catalog sources for the series API."""

from __future__ import annotations

from typing import Any, Callable

from yt_dlp import YoutubeDL

from yt_dlp_emby.dropout_manifest import DropoutSeason
from yt_dlp_emby.dropout_seasons import discover_dropout_seasons
from yt_dlp_emby.extract import _base_opts
from yt_dlp_emby.dropout import resolve_emby_target

FetchHtml = Callable[[str], str]


class ChannelDiscoverError(Exception):
    def __init__(self, url: str, message: str) -> None:
        super().__init__(message)
        self.url = url
        self.message = message


def _ydl_urlopen(url: str, *, cookiefile: str | None) -> str:
    opts = _base_opts(cookiefile=cookiefile, verbose=False)
    with YoutubeDL(opts) as ydl:
        return ydl.urlopen(url).read().decode("utf-8", "replace")


def discover_dropout_source(
    url: str,
    *,
    cookiefile: str | None,
    fetch_html: FetchHtml | None = None,
) -> list[dict[str, Any]]:
    fetch = fetch_html or (lambda target: _ydl_urlopen(target, cookiefile=cookiefile))
    raw = discover_dropout_seasons(url, fetch_html=fetch)
    seasons: list[dict[str, Any]] = []
    for item in raw:
        dropout = int(item["dropout"])
        seasons.append(
            {
                "dropout": dropout,
                "url": str(item["url"]),
                "to_season": int(item.get("to_season", dropout)),
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
    return any(
        token in lowered
        for token in ("/channel/", "/c/", "/user/", "/@", "/playlists")
    )


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
        raise ChannelDiscoverError(text, str(exc) or "channel extract failed") from exc
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


def dropout_episode_rows(
    season: DropoutSeason,
    listings: list[Any],
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
            }
        )
    return rows


def youtube_episode_rows(season: dict[str, Any], playlist) -> list[dict[str, Any]]:
    skip_ids = {str(x) for x in (season.get("skip_ids") or [])}
    to_season = season.get("to_season") or 1
    rows: list[dict[str, Any]] = []
    for episode in playlist.episodes:
        vid = episode.video_id
        skipped = vid in skip_ids
        rows.append(
            {
                "id": vid,
                "title": episode.title,
                "url": episode.webpage_url or f"https://www.youtube.com/watch?v={vid}",
                "source_episode": episode.playlist_index,
                "skipped": skipped,
                "mapped_season": to_season,
                "mapped_episode": episode.playlist_index,
                "mapped_title": episode.title,
            }
        )
    return rows
