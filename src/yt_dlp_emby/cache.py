"""On-disk cache of per-video yt-dlp metadata."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, NoReturn

from yt_dlp_emby.config import ConfigError
from yt_dlp_emby.extract import DropoutListing, EpisodeInfo, PlaylistInfo

CACHE_FILENAME = ".yt-emby-cache.json"
DROPOUT_CACHE_DIRNAME = "cache"
DROPOUT_CACHE_FILENAME = "dropout.json"
LEGACY_DROPOUT_CACHE_FILENAME = ".yt-emby-dropout.json"


def quarantine_corrupt(path: Path, exc: Exception) -> NoReturn:
    backup = path.with_name(f"{path.name}.corrupt-{int(time.time())}")
    try:
        shutil.copy2(path, backup)
    except OSError:
        backup = path
    raise ConfigError(f"corrupt index {path} (backed up to {backup}): {exc}") from exc


def load_json_object(path: Path, *, kind: str = "index") -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        quarantine_corrupt(path, exc)
    if not isinstance(data, dict):
        quarantine_corrupt(path, TypeError(f"{kind} root is not an object"))
    return data


def load_cache(series: Path) -> dict[str, dict]:
    path = series / CACHE_FILENAME
    if not path.is_file():
        return {}
    data = load_json_object(path, kind="cache")
    videos = data.get("videos")
    if isinstance(videos, dict):
        return {str(key): value for key, value in videos.items() if isinstance(value, dict)}
    return {}


def atomic_write_private(
    path: Path,
    data: bytes | str,
    *,
    mode: int = 0o600,
    encoding: str = "utf-8",
) -> None:
    """Write `data` via a unique tmp file, fsync, then replace. Default mode 0600."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = data.encode(encoding) if isinstance(data, str) else data
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
        os.chmod(path, mode)
        try:
            dir_fd = os.open(str(path.parent), os.O_RDONLY)
        except OSError:
            dir_fd = -1
        if dir_fd >= 0:
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path, text: str, *, mode: int = 0o600) -> None:
    atomic_write_private(path, text, mode=mode)


@contextmanager
def file_lock(path: Path) -> Iterator[None]:
    """Inter-process lock on a sidecar `.lock` next to `path`."""
    lock_path = path.with_name(path.name + ".lock")
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o600)
    try:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX)
        except ImportError:
            pass
        yield
    finally:
        try:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
        except (ImportError, OSError):
            pass
        os.close(fd)


def save_cache(series: Path, cache: dict[str, dict]) -> None:
    payload = {"videos": cache}
    path = series / CACHE_FILENAME
    with file_lock(path):
        atomic_write_text(
            path,
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
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
    except (OSError, json.JSONDecodeError) as exc:
        quarantine_corrupt(path, exc)
    seasons = data.get("seasons") if isinstance(data, dict) else None
    if not isinstance(seasons, dict):
        quarantine_corrupt(path, TypeError("dropout cache root.seasons is not an object"))
    result: dict[str, list[dict]] = {}
    for key, value in seasons.items():
        if isinstance(value, list):
            result[str(key)] = [item for item in value if isinstance(item, dict)]
    return result


def save_dropout_season_cache(path: Path, seasons: dict[str, list[dict]]) -> None:
    payload = {"seasons": seasons}
    with file_lock(path):
        atomic_write_text(
            path,
            json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
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
