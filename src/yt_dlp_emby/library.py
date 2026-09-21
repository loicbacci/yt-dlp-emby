"""Emby folder layout and the per-series .yt-emby.json index."""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from yt_dlp_emby.cache import atomic_write_text, file_lock, load_json_object, quarantine_corrupt

INDEX_FILENAME = ".yt-emby.json"
RENAME_TMP_PREFIX = ".__yt_dlp_emby_tmp__"
MAX_EPISODE_FILENAME_BYTES = 200
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
    height: int | None = None
    season: int | None = None


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


def series_relpath(relative: str) -> str:
    """Return a library-relative series folder, rejecting path traversal."""
    raw = (relative or "").strip()
    if not raw:
        raise ValueError("series path is empty")
    candidate = Path(raw)
    if candidate.is_absolute() or any(part == ".." for part in candidate.parts):
        raise ValueError("series path must stay inside the library")
    return str(candidate)


def series_library_path(library: Path, relative: str) -> Path:
    """Join a series folder onto the library root without escaping it."""
    rel = series_relpath(relative)
    library_resolved = library.resolve()
    resolved = (library / rel).resolve()
    if not resolved.is_relative_to(library_resolved):
        raise ValueError("series path must stay inside the library")
    return resolved


def series_dir(library: Path, channel_name: str) -> Path:
    return library / sanitize_filename(channel_name)


def season_folder_name(season: int) -> str:
    if season == 0:
        return "Specials"
    return f"Season {season}"


def season_dir(series: Path, season: int) -> Path:
    """Prefer an existing folder, including zero-padded names like Season 01."""
    if season == 0:
        return series / season_folder_name(0)
    unpadded = series / season_folder_name(season)
    padded = series / f"Season {season:02d}"
    if unpadded.is_dir() and padded.is_dir():
        from yt_dlp_emby.log import warn

        warn(f"both {unpadded.name} and {padded.name} exist in {series}; using {unpadded.name}")
    if unpadded.is_dir():
        return unpadded
    if padded.is_dir():
        return padded
    return unpadded


def media_exists(season: Path, basename: str) -> bool:
    return (season / f"{basename}.mkv").is_file()


def _truncate_utf8(text: str, max_bytes: int) -> str:
    encoded = text.encode("utf-8")
    if len(encoded) <= max_bytes:
        return text
    while encoded and len(encoded) > max_bytes:
        text = text[:-1]
        encoded = text.encode("utf-8")
    return text.rstrip(" .") or "untitled"


def _disambiguate_stem(dest: Path, stem: str, season: int, episode: int) -> str:
    if not media_exists(dest, stem):
        return stem
    existing = find_episode_mkv(dest, season, episode)
    if existing is not None and existing.stem == stem:
        return stem
    n = 2
    candidate = f"{stem}-{n}"
    while media_exists(dest, candidate):
        n += 1
        candidate = f"{stem}-{n}"
    return candidate


def episode_stem(
    channel_name: str,
    season: int,
    episode: int,
    title: str,
    *,
    dest: Path | None = None,
) -> str:
    prefix = f"{sanitize_filename(channel_name)} - S{season:02d}E{episode:02d} - "
    title_part = sanitize_filename(title)
    max_stem = MAX_EPISODE_FILENAME_BYTES - len(".mkv".encode("utf-8"))
    reserved = len("-99".encode("utf-8"))
    budget = max_stem - reserved
    stem = prefix + title_part
    if len(stem.encode("utf-8")) > budget:
        title_budget = budget - len(prefix.encode("utf-8"))
        title_part = _truncate_utf8(title_part, max(1, title_budget))
        stem = prefix + title_part
    if dest is not None:
        stem = _disambiguate_stem(dest, stem, season, episode)
    return stem


def emby_code(season: int, episode: int) -> str:
    return f"S{season:02d}E{episode:02d}"


def _mkv_is_temp(path: Path) -> bool:
    name = path.name
    if name.startswith(RENAME_TMP_PREFIX):
        return True
    lower = name.lower()
    return path.suffix.lower() != ".mkv" or lower.endswith(_TEMP_MKV)


def _prefer_mkv(current: Path, candidate: Path) -> Path:
    """Prefer a complete file when two .mkv files share the same SxxExx."""
    try:
        current_size = current.stat().st_size
        candidate_size = candidate.stat().st_size
    except OSError:
        return current
    if candidate_size != current_size:
        return candidate if candidate_size > current_size else current
    try:
        return candidate if candidate.stat().st_mtime >= current.stat().st_mtime else current
    except OSError:
        return current


def index_episode_mkvs(season: Path) -> dict[tuple[int, int], Path]:
    """Map (season, episode) -> .mkv with one glob of the folder."""
    found: dict[tuple[int, int], Path] = {}
    if not season.is_dir():
        return found
    for path in sorted(season.glob("*.mkv")):
        if _mkv_is_temp(path):
            continue
        match = _EPISODE_CODE.search(path.name)
        if not match:
            continue
        key = (int(match.group(1)), int(match.group(2)))
        existing = found.get(key)
        found[key] = path if existing is None else _prefer_mkv(existing, path)
    return found


def index_series_mkvs(series: Path) -> dict[tuple[int, int], Path]:
    """Map (season, episode) -> .mkv by walking season/specials folders."""
    found: dict[tuple[int, int], Path] = {}
    if not series.is_dir():
        return found
    for child in sorted(path for path in series.iterdir() if path.is_dir()):
        found.update(index_episode_mkvs(child))
    return found


def find_episode_mkv(season: Path, season_number: int, episode: int) -> Path | None:
    """Return the .mkv for this SxxExx, even if the title in the filename differs."""
    return index_episode_mkvs(season).get((season_number, episode))


def episode_title_from_filename(name: str) -> str:
    stem = name[:-4] if name.lower().endswith(".mkv") else name
    parts = stem.split(" - ", 2)
    return parts[2] if len(parts) >= 3 else stem


def title_key(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def titles_match(left: str, right: str) -> bool:
    """True when titles differ only by case, punctuation, or spacing."""
    a, b = title_key(left), title_key(right)
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
    height = data.get("height")
    season = data.get("season")
    return EpisodeRecord(
        video_id=data["video_id"],
        episode=int(data["episode"]),
        title=data.get("title", ""),
        basename=data.get("basename", ""),
        duration=data.get("duration"),
        filesize=data.get("filesize"),
        upload_date=data.get("upload_date"),
        height=int(height) if isinstance(height, int) and not isinstance(height, bool) else None,
        season=int(season) if isinstance(season, int) and not isinstance(season, bool) else None,
    )


def _playlist_from_dict(playlist_id: str, data: dict) -> PlaylistRecord:
    episodes = {
        video_id: _episode_from_dict(raw) for video_id, raw in (data.get("episodes") or {}).items()
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
    empty = LibraryIndex(channel_id="", channel_name=series.name)
    if not path.is_file():
        return empty
    data = load_json_object(path, kind="index")
    try:
        playlists = {
            playlist_id: _playlist_from_dict(playlist_id, raw)
            for playlist_id, raw in (data.get("playlists") or {}).items()
        }
        return LibraryIndex(
            channel_id=data.get("channel_id", ""),
            channel_name=data.get("channel_name", series.name),
            playlists=playlists,
        )
    except (TypeError, KeyError, ValueError, AttributeError) as exc:
        quarantine_corrupt(path, exc)


def save_index(series: Path, index: LibraryIndex) -> None:
    payload = {
        "channel_id": index.channel_id,
        "channel_name": index.channel_name,
        "playlists": {
            playlist_id: {
                "playlist_id": record.playlist_id,
                "season": record.season,
                "title": record.title,
                "description": record.description,
                "episodes": {video_id: asdict(ep) for video_id, ep in record.episodes.items()},
            }
            for playlist_id, record in index.playlists.items()
        },
    }
    path = series / INDEX_FILENAME
    with file_lock(path):
        atomic_write_text(
            path,
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        )
