"""Emby folder layout and the per-series .yt-emby.json index."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

INDEX_FILENAME = ".yt-emby.json"
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


@dataclass
class EpisodeRecord:
    video_id: str
    episode: int
    title: str
    basename: str
    duration: float | None = None
    filesize: int | None = None
    upload_date: str | None = None


@dataclass
class PlaylistRecord:
    playlist_id: str
    season: int
    title: str
    description: str = ""
    episodes: dict[str, EpisodeRecord] = field(default_factory=dict)


@dataclass
class LibraryIndex:
    channel_id: str
    channel_name: str
    playlists: dict[str, PlaylistRecord] = field(default_factory=dict)


def sanitize_filename(name: str) -> str:
    cleaned = _ILLEGAL.sub(" - ", name)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or "untitled"


def series_dir(library: Path, channel_name: str) -> Path:
    return library / sanitize_filename(channel_name)


def season_folder_name(season: int) -> str:
    return f"Season {season:02d}"


def season_dir(series: Path, season: int) -> Path:
    return series / season_folder_name(season)


def media_exists(season: Path, basename: str) -> bool:
    return (season / f"{basename}.mkv").is_file()


def episode_stem(channel_name: str, season: int, episode: int, title: str) -> str:
    return (
        f"{sanitize_filename(channel_name)} - "
        f"S{season:02d}E{episode:02d} - "
        f"{sanitize_filename(title)}"
    )


def assign_season(index: LibraryIndex, playlist_id: str, forced: int | None) -> int:
    if forced is not None:
        return forced
    existing = index.playlists.get(playlist_id)
    if existing:
        return existing.season
    used = {record.season for record in index.playlists.values()}
    season = 1
    while season in used:
        season += 1
    return season


def _episode_from_dict(data: dict) -> EpisodeRecord:
    return EpisodeRecord(
        video_id=data["video_id"],
        episode=int(data["episode"]),
        title=data.get("title", ""),
        basename=data.get("basename", ""),
        duration=data.get("duration"),
        filesize=data.get("filesize"),
        upload_date=data.get("upload_date"),
    )


def _playlist_from_dict(playlist_id: str, data: dict) -> PlaylistRecord:
    episodes = {
        video_id: _episode_from_dict(raw)
        for video_id, raw in (data.get("episodes") or {}).items()
    }
    return PlaylistRecord(
        playlist_id=data.get("playlist_id", playlist_id),
        season=int(data["season"]),
        title=data.get("title", ""),
        description=data.get("description", ""),
        episodes=episodes,
    )


def load_index(series: Path) -> LibraryIndex:
    path = series / INDEX_FILENAME
    if not path.is_file():
        return LibraryIndex(channel_id="", channel_name=series.name)
    data = json.loads(path.read_text(encoding="utf-8"))
    playlists = {
        playlist_id: _playlist_from_dict(playlist_id, raw)
        for playlist_id, raw in (data.get("playlists") or {}).items()
    }
    return LibraryIndex(
        channel_id=data.get("channel_id", ""),
        channel_name=data.get("channel_name", series.name),
        playlists=playlists,
    )


def save_index(series: Path, index: LibraryIndex) -> None:
    series.mkdir(parents=True, exist_ok=True)
    payload = {
        "channel_id": index.channel_id,
        "channel_name": index.channel_name,
        "playlists": {
            playlist_id: {
                "playlist_id": record.playlist_id,
                "season": record.season,
                "title": record.title,
                "description": record.description,
                "episodes": {
                    video_id: asdict(ep) for video_id, ep in record.episodes.items()
                },
            }
            for playlist_id, record in index.playlists.items()
        },
    }
    (series / INDEX_FILENAME).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
