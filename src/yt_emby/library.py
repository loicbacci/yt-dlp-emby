"""Emby folder layout and the per-series .yt-emby.json index."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

INDEX_FILENAME = ".yt-emby.json"
_ILLEGAL = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_EPISODE_CODE = re.compile(r"S(\d{2})E(\d+)", re.I)
_TEMP_MKV = (".temp.mkv", ".tmp.mkv")


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
    return f"Season {season}"


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


def emby_code(season: int, episode: int) -> str:
    return f"S{season:02d}E{episode:02d}"


def index_episode_mkvs(season: Path) -> dict[tuple[int, int], Path]:
    """Map (season, episode) -> .mkv with one glob of the folder."""
    found: dict[tuple[int, int], Path] = {}
    if not season.is_dir():
        return found
    for path in sorted(season.glob("*.mkv")):
        name = path.name.lower()
        if path.suffix.lower() != ".mkv" or name.endswith(_TEMP_MKV):
            continue
        match = _EPISODE_CODE.search(path.name)
        if not match:
            continue
        key = (int(match.group(1)), int(match.group(2)))
        found.setdefault(key, path)
    return found


def find_episode_mkv(season: Path, season_number: int, episode: int) -> Path | None:
    """Return the .mkv for this SxxExx, even if the title in the filename differs."""
    return index_episode_mkvs(season).get((season_number, episode))


def episode_title_from_filename(name: str) -> str:
    stem = name[:-4] if name.lower().endswith(".mkv") else name
    parts = stem.split(" - ", 2)
    return parts[2] if len(parts) >= 3 else stem


def titles_match(left: str, right: str) -> bool:
    """True when titles differ only by case, punctuation, or spacing."""

    def norm(value: str) -> str:
        return re.sub(r"[^a-z0-9]+", "", value.casefold())

    a, b = norm(left), norm(right)
    return bool(a) and a == b


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
