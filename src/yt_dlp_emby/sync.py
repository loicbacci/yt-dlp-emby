"""Diff a live playlist against the local index and move/rename files."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from yt_dlp_emby.extract import EpisodeInfo, PlaylistInfo
from yt_dlp_emby.library import RENAME_TMP_PREFIX, EpisodeRecord, PlaylistRecord, episode_stem


class ActionKind(Enum):
    ADD = "add"
    REMOVE = "remove"
    REPLACE = "replace"
    RENAME = "rename"
    REFRESH = "refresh"


@dataclass
class SyncAction:
    kind: ActionKind
    video_id: str
    season: int
    episode: int | None = None
    live: EpisodeInfo | None = None
    stored: EpisodeRecord | None = None
    old_basename: str | None = None
    new_basename: str | None = None
    old_season: int | None = None


FILESIZE_JITTER_BYTES = 10 * 1024 * 1024
FILESIZE_JITTER_RATIO = 0.05


def content_changed(stored: EpisodeRecord, live: EpisodeInfo) -> bool:
    if stored.duration is not None and live.duration is not None:
        if abs(stored.duration - live.duration) > 1:
            return True
    if stored.filesize is not None and live.filesize is not None:
        delta = abs(stored.filesize - live.filesize)
        if delta == 0:
            return False
        if delta > FILESIZE_JITTER_BYTES and delta > FILESIZE_JITTER_RATIO * stored.filesize:
            return True
    return False


def plan_sync(
    playlist: PlaylistInfo,
    record: PlaylistRecord | None,
    season: int,
) -> list[SyncAction]:
    stored_map = dict(record.episodes) if record else {}
    live_ids = {episode.video_id for episode in playlist.episodes}
    actions: list[SyncAction] = []

    for video_id, stored in stored_map.items():
        if video_id not in live_ids:
            actions.append(
                SyncAction(
                    kind=ActionKind.REMOVE,
                    video_id=video_id,
                    season=season,
                    episode=stored.episode,
                    stored=stored,
                    old_basename=stored.basename,
                    old_season=stored.season if stored.season is not None else record.season,
                )
            )

    channel = playlist.channel
    for live in sorted(playlist.episodes, key=lambda item: item.playlist_index):
        target = live.playlist_index
        new_basename = episode_stem(channel, season, target, live.title)
        stored = stored_map.get(live.video_id)
        if stored is None:
            actions.append(
                SyncAction(
                    kind=ActionKind.ADD,
                    video_id=live.video_id,
                    season=season,
                    episode=target,
                    live=live,
                    new_basename=new_basename,
                )
            )
            continue
        if content_changed(stored, live):
            actions.append(
                SyncAction(
                    kind=ActionKind.REPLACE,
                    video_id=live.video_id,
                    season=season,
                    episode=target,
                    live=live,
                    stored=stored,
                    old_basename=stored.basename,
                    new_basename=new_basename,
                )
            )
            continue
        if stored.episode != target or stored.basename != new_basename:
            actions.append(
                SyncAction(
                    kind=ActionKind.RENAME,
                    video_id=live.video_id,
                    season=season,
                    episode=target,
                    live=live,
                    stored=stored,
                    old_basename=stored.basename,
                    new_basename=new_basename,
                )
            )
            continue
        actions.append(
            SyncAction(
                kind=ActionKind.REFRESH,
                video_id=live.video_id,
                season=season,
                episode=target,
                live=live,
                stored=stored,
                old_basename=stored.basename,
                new_basename=new_basename,
            )
        )
    return actions


def episode_files(folder: Path, stem: str) -> list[Path]:
    if not folder.is_dir():
        return []
    matches: list[Path] = []
    for path in folder.iterdir():
        if not path.is_file():
            continue
        name = path.name
        if not name.startswith(stem):
            continue
        rest = name[len(stem) :]
        if rest.startswith(".") or rest.startswith("-"):
            matches.append(path)
    return matches


def move_episode_files(season_dir: Path, stem: str, destination: Path) -> list[Path]:
    destination.mkdir(parents=True, exist_ok=True)
    moved: list[Path] = []
    for path in episode_files(season_dir, stem):
        target = destination / path.name
        try:
            shutil.move(str(path), str(target))
        except OSError:
            continue
        moved.append(target)
    return moved


def rename_episode_files(season_dir: Path, old_stem: str, new_stem: str) -> None:
    if old_stem == new_stem:
        return
    for path in episode_files(season_dir, old_stem):
        rest = path.name[len(old_stem) :]
        path.rename(season_dir / f"{new_stem}{rest}")


def recover_rename_temps(season_dir: Path) -> None:
    """Finish two-phase renames left behind after a crash."""
    if not season_dir.is_dir():
        return
    for path in list(season_dir.iterdir()):
        if not path.name.startswith(RENAME_TMP_PREFIX):
            continue
        final_name = path.name[len(RENAME_TMP_PREFIX) :]
        if not final_name:
            continue
        dest = season_dir / final_name
        try:
            if dest.exists():
                path.unlink()
            else:
                path.rename(dest)
        except OSError:
            continue


def apply_renames(season_dir: Path, pairs: list[tuple[str, str]]) -> None:
    recover_rename_temps(season_dir)
    pending: list[tuple[str, str]] = []
    for old_stem, new_stem in pairs:
        if not old_stem or not new_stem or old_stem == new_stem:
            continue
        tmp = f"{RENAME_TMP_PREFIX}{new_stem}"
        rename_episode_files(season_dir, old_stem, tmp)
        pending.append((tmp, new_stem))
    for tmp, new_stem in pending:
        rename_episode_files(season_dir, tmp, new_stem)
