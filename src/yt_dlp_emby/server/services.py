"""Typed domain services used by the web coordinator and private workers.

The API layer owns admission and persistence. These functions own provider,
configuration, library and planning decisions and return serializable values;
they do not start a CLI process or publish UI events through module globals.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from yt_dlp_emby.config import ConfigError, config_target_path, load_config_values
from yt_dlp_emby.dropout_manifest import DropoutSeries
from yt_dlp_emby.extract import extract_dropout_season, extract_playlist
from yt_dlp_emby.library import index_episode_mkvs, series_library_path
from yt_dlp_emby.server.manifests import atomic_write_manifest_text
from yt_dlp_emby.server.series import (
    _confined_import_path,
    _cookie_path_for_platform,
    _dropout_series_to_yaml,
    _load_root_yaml,
    locate_series,
    series_folder_rel,
)
from yt_dlp_emby.server.series_discover import discover_dropout_source, merge_dropout_seasons
from yt_dlp_emby.youtube_manifest import YoutubeSeries

Emit = Callable[[dict[str, Any]], None]


@dataclass(frozen=True)
class ConfigSnapshot:
    path: str
    revision: str
    values: dict[str, str]


@dataclass(frozen=True)
class LibrarySnapshot:
    status: str
    series_exists: bool | None
    episodes: tuple[tuple[int, int], ...] | None
    episode_fingerprints: tuple[tuple[int, int, int, int], ...] | None
    provider_index: dict[str, Any] | None
    season_folders: tuple[str, ...]
    revision: str | None
    scanned_at: str
    mount_identity: str | None = None
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["episodes"] = (
            [list(pair) for pair in self.episodes] if self.episodes is not None else None
        )
        value["episode_fingerprints"] = (
            [list(row) for row in self.episode_fingerprints]
            if self.episode_fingerprints is not None
            else None
        )
        return value


@dataclass(frozen=True)
class ProviderListing:
    platform: str
    source_index: int
    season_index: int
    source_season: int | None
    destination_season: int | None
    episode: int
    identity: str
    title: str
    url: str
    enabled: bool = True
    skipped: bool = False
    mapped_episode: int | None = None
    mapped_title: str | None = None
    playlist_id: str | None = None
    playlist_title: str | None = None
    channel: str | None = None
    description: str = ""
    duration: float | None = None
    filesize: int | None = None
    season_title: str | None = None
    empty_listing: bool = False
    source_url: str | None = None


@dataclass(frozen=True)
class RefreshTargetResult:
    target: dict[str, str]
    view: dict[str, Any]
    plan: dict[str, Any]
    config_updates: dict[str, Any] = field(default_factory=dict)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            **self.target,
            "ok": self.error is None,
            "error": self.error,
            "view": self.view,
            "plan": self.plan,
            "config_updates": self.config_updates,
        }


def _digest(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _snapshot_from_dict(raw: Any) -> LibrarySnapshot:
    if not isinstance(raw, Mapping):
        return LibrarySnapshot("unavailable", None, None, None, None, (), None, "")
    episodes = raw.get("episodes")
    fingerprints = raw.get("episode_fingerprints")
    return LibrarySnapshot(
        status=str(raw.get("status") or "unavailable"),
        series_exists=raw.get("series_exists")
        if isinstance(raw.get("series_exists"), bool)
        else None,
        episodes=tuple(
            (int(row[0]), int(row[1]))
            for row in episodes
            if isinstance(row, list) and len(row) >= 2
        )
        if isinstance(episodes, list)
        else None,
        episode_fingerprints=tuple(
            (int(row[0]), int(row[1]), int(row[2]), int(row[3]))
            for row in fingerprints
            if isinstance(row, list) and len(row) >= 4
        )
        if isinstance(fingerprints, list)
        else None,
        provider_index=raw.get("provider_index")
        if isinstance(raw.get("provider_index"), dict)
        else None,
        season_folders=tuple(str(value) for value in raw.get("season_folders", [])),
        revision=str(raw["revision"]) if raw.get("revision") is not None else None,
        scanned_at=str(raw.get("scanned_at") or ""),
        mount_identity=str(raw["mount_identity"]) if raw.get("mount_identity") else None,
        error=str(raw["error"]) if raw.get("error") else None,
    )


def config_revision_for(
    settings_revision: str,
    manifest_revision: str | None,
    root_revision: str | None = None,
    effective_revision: str | None = None,
) -> str:
    """Combine config inputs without retaining potentially sensitive values."""
    return _digest(
        {
            "settings": settings_revision,
            "root_manifest": root_revision,
            "series_manifest": manifest_revision,
            "effective_overrides": effective_revision,
        }
    )


def current_configuration_revision(
    data_dir: Path, environ: Mapping[str, str], platform: str, slug: str
) -> str:
    """Hash this target's effective config without inspecting the media library.

    The full manifest file hashes remain on the cached view for compare-and-swap
    writes. This semantic revision excludes sibling series so editing one show
    does not stale every other cached target in the same YAML file.
    """
    return str(configuration_revisions(data_dir, environ, platform, slug)["config_revision"] or "")


def configuration_revisions(
    data_dir: Path, environ: Mapping[str, str], platform: str, slug: str
) -> dict[str, str | None]:
    """Return full-file audit hashes and the target-scoped semantic revision."""
    loc, series = locate_series(data_dir, platform, slug)
    config = load_config_snapshot(data_dir, environ)
    root_data, root_path = _load_root_yaml(data_dir, platform)
    series_file = _confined_import_path(data_dir, loc.file)
    manifest_revision = (
        hashlib.sha256(series_file.read_bytes()).hexdigest()
        if series_file is not None and series_file.is_file()
        else None
    )
    root_manifest_revision = (
        hashlib.sha256(root_path.read_bytes()).hexdigest() if root_path.is_file() else None
    )
    # Keep config.path in the hash so switching selected TOML files invalidates
    # plans even when both files happen to contain identical values.
    settings_revision = _digest({"path": config.path, "values": config.values})
    root_globals = (
        {key: value for key, value in root_data.items() if key != "series"}
        if isinstance(root_data, Mapping)
        else {}
    )
    target_revision = _digest(
        {
            "platform": platform,
            "file": loc.file,
            "inline": loc.inline,
            "index": loc.index,
            "series": asdict(series),
        }
    )
    root_semantic_revision = _digest(root_globals)
    effective_revision = _effective_revision(environ)
    semantic_revision = config_revision_for(
        settings_revision, target_revision, root_semantic_revision, effective_revision
    )
    return {
        "settings_revision": config.revision,
        "root_manifest_revision": root_manifest_revision,
        "manifest_revision": manifest_revision,
        "effective_revision": effective_revision,
        "config_revision": semantic_revision,
    }


def _effective_revision(environ: Mapping[str, str]) -> str:
    from yt_dlp_emby.config import env_value

    return _digest(
        {
            key: env_value(environ, key)
            for key in (
                "LIBRARY",
                "OLD_DIR",
                "STAGING",
                "CONFIG",
                "COOKIES",
                "SONARR_URL",
                "SONARR_API_KEY",
            )
        }
    )


def load_config_snapshot(data_dir: Path, environ: Mapping[str, str]) -> ConfigSnapshot:
    """Load canonical TOML without creating the config or its parent directory."""
    path = config_target_path(None, environ, data_dir)
    values = load_config_values(path) if path.is_file() else {}
    content = path.read_bytes() if path.is_file() else b""
    return ConfigSnapshot(str(path), hashlib.sha256(content).hexdigest(), values)


def library_snapshot(
    library: Path,
    series_path: str,
    *,
    expected_mount_identity: str | None = None,
) -> LibrarySnapshot:
    """Inspect media without creating directories or treating errors as empty."""
    now = datetime.now(timezone.utc).isoformat()
    try:
        root = library.resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(str(root))
        mount = _mount_identity(root)
        if expected_mount_identity and mount != expected_mount_identity:
            return LibrarySnapshot(
                status="unavailable",
                series_exists=None,
                episodes=None,
                episode_fingerprints=None,
                provider_index=None,
                season_folders=(),
                revision=None,
                scanned_at=now,
                mount_identity=mount,
                error="library mount changed",
            )
        folder = series_library_path(root, series_path)
        # Resolve and guard traversal before inspecting. Missing show is a
        # successful empty snapshot; missing root is handled above as unavailable.
        if not folder.exists():
            return LibrarySnapshot("ready", False, (), (), {}, (), _digest([]), now, mount)
        if not folder.is_dir():
            raise NotADirectoryError(str(folder))
        indexed: dict[tuple[int, int], Path] = {}
        for season_folder in sorted(folder.iterdir()):
            try:
                if not season_folder.is_dir() or not season_folder.resolve().is_relative_to(folder):
                    continue
            except OSError:
                continue
            for key, value in index_episode_mkvs(season_folder).items():
                indexed[key] = value
        episodes = tuple(sorted(indexed))
        fingerprints = tuple(
            (
                season,
                episode,
                indexed[(season, episode)].stat().st_size,
                indexed[(season, episode)].stat().st_mtime_ns,
            )
            for season, episode in episodes
        )
        provider_index: dict[str, Any] = {}
        index_path = folder / ".yt-emby.json"
        if index_path.is_file():
            loaded = json.loads(index_path.read_text(encoding="utf-8"))
            if not isinstance(loaded, dict) or not isinstance(loaded.get("playlists", {}), dict):
                raise ValueError("invalid .yt-emby.json index")
            provider_index = loaded
        season_folders = tuple(
            sorted(
                item.name
                for item in folder.iterdir()
                if item.is_dir() and item.resolve().is_relative_to(folder)
            )
        )
        revision = _digest(
            {
                "mount": mount,
                "episodes": fingerprints,
                "index": provider_index,
                "season_folders": season_folders,
            }
        )
        return LibrarySnapshot(
            status="ready",
            series_exists=True,
            episodes=episodes,
            episode_fingerprints=fingerprints,
            provider_index=provider_index,
            season_folders=season_folders,
            revision=revision,
            scanned_at=now,
            mount_identity=mount,
        )
    except (OSError, ValueError) as exc:
        return LibrarySnapshot(
            status="unavailable",
            series_exists=None,
            episodes=None,
            episode_fingerprints=None,
            provider_index=None,
            season_folders=(),
            revision=None,
            scanned_at=now,
            mount_identity=None,
            error=str(exc)[:300],
        )


def _mount_identity(path: Path) -> str | None:
    try:
        target = path.resolve(strict=True)
        best: tuple[int, str] | None = None
        for line in Path("/proc/self/mountinfo").read_text(encoding="utf-8").splitlines():
            left, _separator, right = line.partition(" - ")
            fields, tail = left.split(), right.split()
            if len(fields) < 5 or len(tail) < 2:
                continue
            mountpoint = Path(fields[4].replace("\\040", " ").replace("\\134", "\\"))
            try:
                if not target.is_relative_to(mountpoint):
                    continue
            except ValueError:
                continue
            identity = "|".join((fields[2], fields[3], str(mountpoint), tail[0], tail[1]))
            rank = len(mountpoint.parts)
            if best is None or rank > best[0]:
                best = (rank, identity)
        if best is not None:
            return best[1]
        stat = target.stat()
        return f"local|{stat.st_dev}:{stat.st_ino}"
    except (OSError, ValueError):
        return None


def _resolved_library(data_dir: Path, platform: str, environ: Mapping[str, str]) -> Path:
    config = load_config_snapshot(data_dir, environ)
    manifest, manifest_path = _load_root_yaml(data_dir, platform)
    from yt_dlp_emby.config import env_value

    env_library = env_value(environ, "LIBRARY")
    manifest_library = (manifest or {}).get("library")
    config_library = config.values.get("library")
    raw = env_library or manifest_library or config_library
    if not raw:
        raise ConfigError("library is not configured")
    candidate = Path(raw)
    if candidate.is_absolute():
        return candidate
    if env_library:
        base = data_dir
    elif manifest_library:
        base = manifest_path.parent
    else:
        config_path = Path(config.path)
        base = config_path.parent if config_path.is_absolute() else data_dir / config_path.parent
    return base / candidate


def plan_series(
    *,
    platform: str,
    slug: str,
    listings: Sequence[ProviderListing],
    disk: LibrarySnapshot,
    config_revision: str,
    options: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Pure plan builder. Unknown disk state blocks actions instead of implying missing files."""
    options = dict(options or {})
    disk_episodes = set(disk.episodes or ())
    force = bool(options.get("force"))
    rows: list[dict[str, Any]] = []
    if platform == "youtube":
        rows.extend(
            _plan_youtube_sync(
                slug,
                listings,
                disk,
                create=bool(options.get("create")),
                force=force,
            )
        )
    for row in () if platform == "youtube" else listings:
        code_season = row.destination_season
        code_episode = row.mapped_episode if row.mapped_episode is not None else row.episode
        code = f"S{code_season:02d}E{code_episode:02d}" if code_season is not None else None
        action: str
        reason: str | None = None
        if row.skipped or not row.enabled:
            action = "skip"
        elif code is None:
            action, reason = "blocked", "episode has no destination mapping"
        elif disk.status != "ready":
            action, reason = "blocked", "library is unavailable"
        elif disk.series_exists is False and not bool(options.get("create")):
            action, reason = "blocked", "series folder is absent; Create is required"
        elif (code_season, code_episode) in disk_episodes:
            action = "replace" if force and platform == "dropout" else "present"
            if not force:
                reason = "already present"
        else:
            action = "download"
        ident = f"{platform}|{slug}|{code or row.identity}"
        action_id = _digest(
            {
                "platform": platform,
                "slug": slug,
                "provider": row.identity,
                "action": action,
                "destination": [code_season, code_episode],
            }
        )
        rows.append(
            {
                "id": f"act_{action_id}",
                "execution_id": ident,
                "platform": platform,
                "slug": slug,
                "code": code,
                "source_id": row.identity,
                "title": row.mapped_title or row.title,
                "url": row.url,
                "action": action,
                "blocked_reason": reason,
                "dest_season": code_season,
                "dest_episode": code_episode,
                "series": row.channel or slug,
                "folder": ("Specials" if code_season == 0 else f"Season {code_season}")
                if code_season is not None
                else "",
                "season_title": row.season_title,
                "provider_identity": row.identity,
                "create_folder": disk.series_exists is False and bool(options.get("create")),
                "action_id": f"act_{action_id}",
                "dependencies": [],
            }
        )
    # A slot occupied by a stale file needs its removal selected alongside a
    # replacement/add. Selecting only one action cannot mutate the other item.
    by_slot: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for item in rows:
        season, episode = item.get("dest_season"), item.get("dest_episode")
        if isinstance(season, int) and isinstance(episode, int):
            by_slot.setdefault((season, episode), []).append(item)
    for items in by_slot.values():
        removals = [item for item in items if item.get("action") == "remove"]
        for item in items:
            if item.get("action") not in {"download", "replace", "rename"}:
                continue
            item["dependencies"] = [remove["id"] for remove in removals]
    revision = _digest(
        {
            "config": config_revision,
            "listing": [asdict(item) for item in listings],
            "disk": disk.revision,
            "options": options,
        }
    )
    plan_id = f"plan_{revision[:24]}"
    readiness = "ready"
    if disk.status != "ready":
        readiness = "blocked"
    elif any("Create is required" in str(item.get("blocked_reason")) for item in rows):
        readiness = "create_required"
    season_counts: dict[tuple[str, int], dict[str, Any]] = {}
    for item in rows:
        dest = item.get("dest_season")
        if not isinstance(dest, int):
            continue
        key = (str(item.get("slug") or slug), dest)
        season = season_counts.setdefault(
            key,
            {
                "slug": key[0],
                "dest_season": dest,
                "folder": item.get("folder") or ("Specials" if dest == 0 else f"Season {dest}"),
                "season_title": item.get("season_title"),
                "download": 0,
                "replace": 0,
                "skip": 0,
                "rename": 0,
                "remove": 0,
                "unmapped": 0,
                "blocked": 0,
            },
        )
        action = str(item.get("action") or "")
        if action in season:
            season[action] += 1
        elif action == "present":
            season["skip"] += 1
        elif action == "blocked":
            season["blocked"] += 1
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "plan_id": plan_id,
        "revision": revision,
        "force": force,
        "readiness": readiness,
        "sources": {
            platform: {
                "ok": disk.status == "ready",
                "error": disk.error,
                "seasons": list(season_counts.values()),
                "items": rows,
            }
        },
        "actions": rows,
        "input_revision": {"config": config_revision, "disk": disk.revision},
    }


def _plan_youtube_sync(
    slug: str,
    listings: Sequence[ProviderListing],
    disk: LibrarySnapshot,
    *,
    create: bool,
    force: bool,
) -> list[dict[str, Any]]:
    """Purely diff cached YouTube listings against the saved per-series index."""
    from yt_dlp_emby.extract import EpisodeInfo, PlaylistInfo
    from yt_dlp_emby.library import EpisodeRecord, PlaylistRecord, season_folder_name
    from yt_dlp_emby.sync import ActionKind, plan_sync

    playlists_index = (disk.provider_index or {}).get("playlists", {})
    if not isinstance(playlists_index, Mapping):
        playlists_index = {}
    grouped: dict[tuple[int, str], list[ProviderListing]] = {}
    for row in listings:
        grouped.setdefault((row.source_index, row.playlist_id or ""), []).append(row)
    out: list[dict[str, Any]] = []
    season_folder_names = set(disk.season_folders)
    for (_source_index, playlist_id), group in grouped.items():
        first = group[0]
        playlist_id = playlist_id or first.identity
        live_episodes = [
            EpisodeInfo(
                video_id=row.identity,
                title=row.title,
                description=row.description,
                playlist_index=row.episode,
                duration=row.duration,
                filesize=row.filesize,
                webpage_url=row.url,
            )
            for row in sorted(group, key=lambda item: item.episode)
            if not row.empty_listing and not row.skipped and row.enabled
        ]
        live = PlaylistInfo(
            playlist_id=playlist_id,
            title=first.playlist_title or f"Season {first.destination_season or 1}",
            description=first.description,
            channel=first.channel or slug,
            channel_id="",
            thumbnail_url=None,
            episodes=live_episodes,
        )
        record: PlaylistRecord | None = None
        raw_record = playlists_index.get(playlist_id)
        if isinstance(raw_record, Mapping):
            episodes: dict[str, EpisodeRecord] = {}
            raw_episodes = raw_record.get("episodes")
            if isinstance(raw_episodes, Mapping):
                for video_id, raw_episode in raw_episodes.items():
                    if not isinstance(raw_episode, Mapping):
                        continue
                    episodes[str(video_id)] = EpisodeRecord(
                        video_id=str(raw_episode.get("video_id") or video_id),
                        episode=int(raw_episode.get("episode") or 0),
                        title=str(raw_episode.get("title") or ""),
                        basename=str(raw_episode.get("basename") or ""),
                        duration=raw_episode.get("duration"),
                        filesize=raw_episode.get("filesize"),
                        upload_date=raw_episode.get("upload_date"),
                        height=raw_episode.get("height"),
                        season=raw_episode.get("season"),
                    )
            record = PlaylistRecord(
                playlist_id=playlist_id,
                season=int(raw_record.get("season") or first.destination_season or 1),
                title=str(raw_record.get("title") or live.title),
                description=str(raw_record.get("description") or ""),
                episodes=episodes,
            )
        destination_season = first.destination_season or 1
        excluded_video_ids = {item.identity for item in group if item.skipped and item.identity}
        for action in plan_sync(live, record, destination_season):
            if action.kind == ActionKind.REMOVE and action.video_id in excluded_video_ids:
                continue
            episode = action.episode or (action.stored.episode if action.stored else 0)
            season = (
                action.old_season
                if action.kind == ActionKind.REMOVE and action.old_season
                else action.season
            )
            code = f"S{season:02d}E{episode:02d}"
            action_name = {
                ActionKind.ADD: "download",
                ActionKind.REPLACE: "replace",
                ActionKind.RENAME: "rename",
                ActionKind.REMOVE: "remove",
                ActionKind.REFRESH: "present",
            }[action.kind]
            if force and action.kind == ActionKind.REFRESH:
                action_name = "replace"
            live_row = next((item for item in group if item.identity == action.video_id), None)
            blocked_reason = None
            if disk.status != "ready":
                action_name, blocked_reason = "blocked", "library is unavailable"
            elif disk.series_exists is False and not create:
                action_name, blocked_reason = (
                    "blocked",
                    "series folder is absent; Create is required",
                )
            folder = season_folder_name(season)
            if (
                season != 0
                and f"Season {season:02d}" in season_folder_names
                and folder not in season_folder_names
            ):
                folder = f"Season {season:02d}"
            action_id = _digest(
                {
                    "slug": slug,
                    "provider": action.video_id,
                    "action": action_name,
                    "destination": [season, episode],
                }
            )
            out.append(
                {
                    "id": f"act_{action_id}",
                    "execution_id": f"youtube|{slug}|{code}",
                    "platform": "youtube",
                    "slug": slug,
                    "series": first.channel or slug,
                    "folder": folder,
                    "season_title": first.playlist_title,
                    "code": code,
                    "source_id": action.video_id,
                    "provider_identity": action.video_id,
                    "title": action.live.title
                    if action.live
                    else action.stored.title
                    if action.stored
                    else action.video_id,
                    "url": live_row.url if live_row else None,
                    "action": action_name,
                    "blocked_reason": blocked_reason,
                    "create_folder": disk.series_exists is False and create,
                    "dest_season": season,
                    "dest_episode": episode,
                    "old_basename": action.old_basename,
                    "new_basename": action.new_basename,
                    "dependencies": [],
                    "action_id": f"act_{action_id}",
                }
            )
    return out


def plan_variant(
    view: Mapping[str, Any], *, force: bool = False, create: bool = False
) -> dict[str, Any]:
    """Build an option variant from cached listing and disk snapshots only."""
    target = view.get("target")
    disk_raw = view.get("disk")
    raw_listings = view.get("provider_listings")
    if not isinstance(target, Mapping) or not isinstance(disk_raw, Mapping):
        raise ValueError("cached view is missing planner inputs")
    if not isinstance(raw_listings, list):
        raise ValueError("cached view is missing provider listings")
    episodes_raw = disk_raw.get("episodes")
    fingerprints_raw = disk_raw.get("episode_fingerprints")
    provider_index_raw = disk_raw.get("provider_index")
    disk = LibrarySnapshot(
        status=str(disk_raw.get("status") or "unavailable"),
        series_exists=disk_raw.get("series_exists"),
        episodes=tuple((int(row[0]), int(row[1])) for row in episodes_raw)
        if isinstance(episodes_raw, list)
        else None,
        episode_fingerprints=(
            tuple((int(row[0]), int(row[1]), int(row[2]), int(row[3])) for row in fingerprints_raw)
            if isinstance(fingerprints_raw, list)
            else None
        ),
        provider_index=(
            dict(provider_index_raw) if isinstance(provider_index_raw, Mapping) else None
        ),
        season_folders=(
            tuple(str(value) for value in disk_raw.get("season_folders", []))
            if isinstance(disk_raw.get("season_folders", []), list)
            else ()
        ),
        revision=str(disk_raw["revision"]) if disk_raw.get("revision") else None,
        scanned_at=str(disk_raw.get("scanned_at") or ""),
        mount_identity=str(disk_raw["mount_identity"]) if disk_raw.get("mount_identity") else None,
        error=str(disk_raw["error"]) if disk_raw.get("error") else None,
    )
    listings = [ProviderListing(**raw) for raw in raw_listings if isinstance(raw, Mapping)]
    return plan_series(
        platform=str(target.get("platform") or ""),
        slug=str(target.get("slug") or ""),
        listings=listings,
        disk=disk,
        config_revision=str(view.get("config_revision") or ""),
        options={"force": force, "create": create},
    )


def _dropout_provider_rows(
    series: DropoutSeries, cookie: str | None, source_indices: set[int]
) -> list[ProviderListing]:
    rows: list[ProviderListing] = []
    for source_index, source in enumerate(series.sources):
        if source_index not in source_indices:
            continue
        for season_index, season in enumerate(source.seasons):
            if not season.enabled:
                continue
            url = season.url or source.url
            if not url:
                continue
            listings = extract_dropout_season(url, cookiefile=cookie)
            allow = set(season.only_episodes) if season.only_episodes else None
            remaps = {r.dropout_episode: r for r in season.remap}
            for listing in listings:
                remap = remaps.get(listing.dropout_episode)
                if remap and remap.skip:
                    skipped = True
                    dest, episode, title = None, None, None
                elif remap:
                    skipped = False
                    dest = (
                        remap.to_season
                        if remap.to_season is not None
                        else season.to_season or season.dropout
                    )
                    episode = remap.to_episode
                    title = remap.title or listing.title
                else:
                    skipped = allow is not None and listing.dropout_episode not in allow
                    dest = season.to_season if season.to_season is not None else season.dropout
                    episode, title = listing.dropout_episode, listing.title
                rows.append(
                    ProviderListing(
                        "dropout",
                        source_index,
                        season_index,
                        season.dropout,
                        dest,
                        listing.dropout_episode,
                        f"{source_index}:{season_index}:{listing.dropout_episode}",
                        listing.title,
                        listing.url,
                        True,
                        skipped,
                        episode,
                        title,
                        source_url=url,
                    )
                )
    return rows


def _youtube_provider_rows(
    series: YoutubeSeries, cookie: str | None, source_indices: set[int]
) -> list[ProviderListing]:
    rows: list[ProviderListing] = []
    for source_index, playlist in enumerate(series.playlists):
        if source_index not in source_indices or not playlist.enabled:
            continue
        info = extract_playlist(playlist.url, cookiefile=cookie)
        destination = playlist.season if playlist.season is not None else source_index + 1
        skips = {str(value) for value in playlist.skip}
        if not info.episodes:
            rows.append(
                ProviderListing(
                    platform="youtube",
                    source_index=source_index,
                    season_index=0,
                    source_season=destination,
                    destination_season=destination,
                    episode=0,
                    identity="",
                    title="",
                    url=playlist.url,
                    playlist_id=info.playlist_id or playlist.url,
                    playlist_title=playlist.title or info.title,
                    channel=info.channel,
                    description=info.description,
                    season_title=playlist.title,
                    source_url=playlist.url,
                    empty_listing=True,
                )
            )
            continue
        for episode in info.episodes:
            rows.append(
                ProviderListing(
                    "youtube",
                    source_index,
                    0,
                    destination,
                    destination,
                    episode.playlist_index,
                    episode.video_id,
                    episode.title,
                    episode.webpage_url or playlist.url,
                    True,
                    episode.video_id in skips,
                    episode.playlist_index,
                    episode.title,
                    playlist_id=info.playlist_id or playlist.url,
                    playlist_title=info.title,
                    channel=info.channel,
                    description=episode.description,
                    duration=episode.duration,
                    filesize=episode.filesize,
                    season_title=playlist.title,
                    source_url=playlist.url,
                )
            )
    return rows


def refresh_target(
    data_dir: Path,
    environ: Mapping[str, str],
    target: Mapping[str, Any],
    emit: Emit | None = None,
) -> dict[str, Any]:
    """Fetch one explicit target, inspect its library and return view/plan proposals."""
    platform, slug = str(target.get("platform") or ""), str(target.get("slug") or "")
    if platform not in {"dropout", "youtube"} or not slug:
        raise ValueError("invalid refresh target")
    loc, series = locate_series(data_dir, platform, slug)
    config = load_config_snapshot(data_dir, environ)
    revisions = configuration_revisions(data_dir, environ, platform, loc.slug)
    manifest_revision = revisions["manifest_revision"]
    root_revision = revisions["root_manifest_revision"]
    effective_revision = revisions["effective_revision"]
    config_revision = str(revisions["config_revision"] or "")
    expected_revision = target.get("expected_revision")
    if expected_revision is not None and str(expected_revision) != config_revision:
        raise ConfigError("configuration changed since the target view was read")
    parts = set(target.get("parts") or ("listings", "disk"))
    cached_view = target.get("cached_view")
    cached_view = cached_view if isinstance(cached_view, Mapping) else {}
    if parts == {"sonarr"}:
        if series.tvdb_id is None:
            return {
                "platform": platform,
                "slug": loc.slug,
                "ok": True,
                "sonarr_skipped": "No TVDB mapping is configured",
                "plan": {"sources": {}},
            }
        try:
            from yt_dlp_emby.config import env_value
            from yt_dlp_emby.sonarr import fetch_episodes_cached_meta

            sonarr_url = env_value(environ, "SONARR_URL") or config.values.get("sonarr_url")
            sonarr_key = env_value(environ, "SONARR_API_KEY") or config.values.get("sonarr_api_key")
            if not sonarr_url or not sonarr_key:
                return {
                    "platform": platform,
                    "slug": loc.slug,
                    "ok": True,
                    "sonarr_skipped": "Sonarr is not configured",
                    "plan": {"sources": {}},
                }
            title, episodes, title_slug = fetch_episodes_cached_meta(
                int(series.tvdb_id),
                base_url=sonarr_url,
                api_key=sonarr_key,
                cache_path=data_dir / "cache" / "sonarr.json",
                force_refetch=True,
            )
            return {
                "platform": platform,
                "slug": loc.slug,
                "ok": True,
                "sonarr": {
                    "title": title,
                    "title_slug": title_slug,
                    "episodes": [asdict(item) for item in episodes],
                    "fetched_at": datetime.now(timezone.utc).isoformat(),
                },
                "plan": {"sources": {}},
            }
        except Exception as exc:
            return {
                "platform": platform,
                "slug": loc.slug,
                "ok": False,
                "error": {"code": "SONARR_FAILED", "message": str(exc)[:300]},
                "plan": {"sources": {}},
            }
    if "disk" in parts:
        library = _resolved_library(data_dir, platform, environ)
        disk = library_snapshot(
            library,
            series_folder_rel(series),
            expected_mount_identity=(
                str(target["expected_mount_identity"])
                if target.get("expected_mount_identity")
                else None
            ),
        )
    else:
        disk = _snapshot_from_dict(cached_view.get("disk"))
    if disk.status != "ready":
        from yt_dlp_emby.server.views import (
            configuration_context_signature,
            source_signature,
        )

        plan = plan_series(
            platform=platform,
            slug=loc.slug,
            listings=[],
            disk=disk,
            config_revision=config_revision,
            options={"force": False, "create": False},
        )
        view = {
            "target": {"platform": platform, "slug": loc.slug},
            "config_revision": config_revision,
            "settings_revision": config.revision,
            "root_manifest_revision": root_revision,
            "manifest_revision": manifest_revision,
            "effective_revision": effective_revision,
            "context_signature": configuration_context_signature(data_dir, environ, platform),
            "refreshed_sources": [],
            "listings_complete": False,
            "listing_revision": None,
            "provider_listings": [],
            "source_signature": source_signature(series),
            "disk": disk.to_dict(),
            "plan_id": plan["plan_id"],
            "stale": True,
            "refreshed_at": datetime.now(timezone.utc).isoformat(),
        }
        if "disk" in parts:
            return RefreshTargetResult(
                {"platform": platform, "slug": loc.slug},
                view,
                plan,
                error=disk.error or "library unavailable",
            ).to_dict()
        raise ConfigError("cached disk inventory is unavailable; refresh disk inventory first")
    source_index = target.get("source_index")
    source_indices = (
        {int(source_index)}
        if source_index is not None
        else set(
            range(
                len(series.sources) if isinstance(series, DropoutSeries) else len(series.playlists)
            )
        )
    )
    source_count = (
        len(series.sources) if isinstance(series, DropoutSeries) else len(series.playlists)
    )
    if any(index < 0 or index >= source_count for index in source_indices):
        raise KeyError("source")
    if emit:
        emit({"event": "progress", "stage": "discover", "target": f"{platform}|{slug}"})
    if "listings" not in parts:
        listings = [ProviderListing(**raw) for raw in cached_view.get("provider_listings", [])]
        if not listings and cached_view.get("listings_complete"):
            listings = []
        source_indices = set(cached_view.get("refreshed_sources", []))
    else:
        try:
            cookie_path = _cookie_path_for_platform(data_dir, platform, environ)
            cookie = str(cookie_path)
        except ConfigError:
            cookie = None
    config_updates: dict[str, Any] = {}
    if "listings" not in parts:
        config_updates = {}
    elif isinstance(series, DropoutSeries):
        # Discovery only proposes canonical edits. The parent verifies the
        # source file hash/revision and applies them while holding its config lock.
        sources = list(series.sources)
        changed = False
        for index in sorted(source_indices):
            if index >= len(sources):
                raise KeyError("source")
            old_source = sources[index]
            if not old_source.url:
                continue
            discovered = discover_dropout_source(old_source.url, cookiefile=cookie)
            merged = merge_dropout_seasons(old_source.seasons, discovered)
            if merged != old_source.seasons:
                changed = True
            sources[index] = type(old_source)(
                url=old_source.url,
                seasons=merged,
            )
        if changed:
            updated = DropoutSeries(
                name=series.name,
                path=series.path,
                sources=tuple(sources),
                tvdb_id=series.tvdb_id,
                tvdb_skip=series.tvdb_skip,
            )
            config_updates = {
                "platform": platform,
                "slug": loc.slug,
                "file": loc.file,
                "expected_hash": hashlib.sha256((data_dir / loc.file).read_bytes()).hexdigest(),
                "inline": bool(loc.inline),
                "index": int(loc.index),
                "series": _dropout_series_to_yaml(updated),
            }
            series = updated
        listings = _dropout_provider_rows(series, cookie, source_indices)
    else:
        listings = _youtube_provider_rows(series, cookie, source_indices)
    plan = plan_series(
        platform=platform,
        slug=loc.slug,
        listings=listings,
        disk=disk,
        config_revision=config_revision,
        options={"force": False, "create": False},
    )
    from yt_dlp_emby.server.views import configuration_context_signature, source_signature

    cache_times = dict(cached_view.get("cache_times") or {})
    refreshed_at = datetime.now(timezone.utc).isoformat()
    if "listings" in parts:
        cache_times["listings"] = refreshed_at
    if "disk" in parts:
        cache_times["disk"] = refreshed_at
    view = {
        "target": {"platform": platform, "slug": loc.slug},
        "config_revision": config_revision,
        "settings_revision": config.revision,
        "root_manifest_revision": root_revision,
        "manifest_revision": manifest_revision,
        "effective_revision": effective_revision,
        "context_signature": configuration_context_signature(data_dir, environ, platform),
        "refreshed_sources": sorted(source_indices),
        "listings_complete": (
            source_indices == set(range(source_count))
            if "listings" in parts
            else bool(cached_view.get("listings_complete"))
        ),
        "listing_revision": _digest([asdict(row) for row in listings]),
        "provider_listings": [asdict(row) for row in listings],
        "sonarr": cached_view.get("sonarr"),
        "cache_times": cache_times,
        "source_signature": source_signature(series),
        "disk": disk.to_dict(),
        "plan_id": plan["plan_id"],
        "stale": disk.status != "ready",
        "refreshed_at": datetime.now(timezone.utc).isoformat(),
    }
    if "sonarr" in parts:
        try:
            if series.tvdb_id is None:
                view["sonarr_error"] = "No TVDB mapping is configured for this show"
            else:
                from yt_dlp_emby.config import env_value
                from yt_dlp_emby.sonarr import fetch_episodes_cached_meta

                sonarr_url = env_value(environ, "SONARR_URL") or config.values.get("sonarr_url")
                sonarr_key = env_value(environ, "SONARR_API_KEY") or config.values.get(
                    "sonarr_api_key"
                )
                if not sonarr_url or not sonarr_key:
                    view["sonarr_error"] = "Sonarr is not configured"
                else:
                    title, episodes, title_slug = fetch_episodes_cached_meta(
                        int(series.tvdb_id),
                        base_url=sonarr_url,
                        api_key=sonarr_key,
                        cache_path=data_dir / "cache" / "sonarr.json",
                        force_refetch=True,
                    )
                    view["sonarr"] = {
                        "title": title,
                        "title_slug": title_slug,
                        "episodes": [asdict(item) for item in episodes],
                        "fetched_at": datetime.now(timezone.utc).isoformat(),
                    }
                    cache_times["sonarr"] = view["sonarr"]["fetched_at"]
                    view.pop("sonarr_error", None)
        except Exception as exc:
            view["sonarr_error"] = str(exc)[:300]
    if emit:
        emit(
            {
                "event": "progress",
                "stage": "planned",
                "target": f"{platform}|{slug}",
                "total": len(listings),
            }
        )
    return RefreshTargetResult(
        {"platform": platform, "slug": loc.slug}, view, plan, config_updates=config_updates
    ).to_dict()


def apply_refresh_updates(data_dir: Path, update: Mapping[str, Any]) -> str:
    """Compare-and-swap a proposed series edit while preserving YAML comments.

    The coordinator calls this after locking configuration writes and before it
    publishes the refreshed view. A worker only returns the proposal.
    """
    from io import StringIO

    from ruamel.yaml import YAML

    from yt_dlp_emby.cache import file_lock
    from yt_dlp_emby.dropout_manifest import parse_dropout_series_file

    platform = str(update.get("platform") or "")
    rel_file = str(update.get("file") or "")
    slug = str(update.get("slug") or "")
    if platform != "dropout" or not rel_file or not slug:
        raise ValueError("invalid refresh config update")
    path = _confined_import_path(data_dir, rel_file)
    if path is None or not path.is_file():
        raise ValueError("refresh target file is unavailable")

    yaml_rt = YAML()
    yaml_rt.preserve_quotes = True
    yaml_rt.width = 4096
    yaml_rt.indent(mapping=2, sequence=4, offset=2)
    with file_lock(path):
        current = path.read_bytes()
        if hashlib.sha256(current).hexdigest() != str(update.get("expected_hash") or ""):
            raise ConfigError("manifest changed during refresh")
        raw = yaml_rt.load(current.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ConfigError("invalid series file")
        entries = raw.get("series")
        if not isinstance(entries, list):
            raise ConfigError("series file no longer contains a series list")
        index = int(update.get("index", -1))
        if index < 0 or index >= len(entries):
            raise ConfigError("series position changed during refresh")
        replacement = update.get("series")
        if not isinstance(replacement, Mapping):
            raise ConfigError("invalid refreshed series proposal")
        typed = parse_dropout_series_file({"series": [dict(replacement)]}, path)
        if len(typed) != 1:
            raise ConfigError("invalid refreshed series proposal")
        current_series = parse_dropout_series_file({"series": entries}, path)
        if (
            index >= len(current_series)
            or current_series[index].name.casefold()
            != str(replacement.get("name") or "").casefold()
        ):
            raise ConfigError("series position changed during refresh")
        from yt_dlp_emby.server.yaml_merge import merge_round_trip

        entries[index] = merge_round_trip(entries[index], replacement)
        raw["series"] = entries
        output = StringIO()
        yaml_rt.dump(raw, output)
        atomic_write_manifest_text(path, output.getvalue())
        return hashlib.sha256(path.read_bytes()).hexdigest()


def download_selected(
    data_dir: Path,
    environ: Mapping[str, str],
    plan_id: str,
    ids: Sequence[str],
    *,
    force: bool = False,
    create: bool = False,
    operation_context: Any = None,
) -> dict[str, Any]:
    """Validate explicit selections before dispatching the provider executor."""
    if not ids or len(set(ids)) != len(ids):
        raise ValueError("download selection must contain unique action IDs")
    if not plan_id or not all(isinstance(value, str) and value for value in ids):
        raise ValueError("plan_id and explicit action IDs are required")
    # Worker inputs carry the immutable plan rows. The executor adapter will
    # pass only these rows to existing media logic using an operation context.
    selected = (
        operation_context.get("selected_actions")
        if isinstance(operation_context, Mapping)
        else getattr(operation_context, "selected_actions", None)
    )
    rows = {str(row.get("id")): row for row in selected or [] if isinstance(row, Mapping)}
    if not rows or set(ids) - set(rows):
        raise ValueError("selected actions do not belong to the supplied plan revision")
    if any(rows[action_id].get("action") != "download" for action_id in ids):
        raise ValueError("selection contains a non-executable action")
    if (
        any(
            rows[action_id].get("platform") == "dropout"
            and rows[action_id].get("action") == "replace"
            for action_id in ids
        )
        and not force
    ):
        raise ValueError("replacement requires Force")
    if any(rows[action_id].get("create_folder") for action_id in ids) and not create:
        raise ValueError("creating a show folder requires Create")
    context_plan_id = (
        operation_context.get("plan_id")
        if isinstance(operation_context, Mapping)
        else getattr(operation_context, "plan_id", None)
    )
    if context_plan_id is not None and str(context_plan_id) != plan_id:
        raise ValueError("selected actions do not belong to the supplied plan revision")
    for action_id in ids:
        dependencies = rows[action_id].get("dependencies") or []
        if not set(dependencies).issubset(ids):
            raise ValueError("selected action requires an explicitly selected dependency")

    # Recheck the effective config before execution. Inventory is deliberately
    # not rescanned here: each destination is checked immediately before its
    # download, avoiding another full walk of a remote library tree.
    cached_views = (
        operation_context.get("cached_views")
        if isinstance(operation_context, Mapping)
        else getattr(operation_context, "cached_views", None)
    )
    cached_by_target = {
        (str(item.get("platform") or ""), str(item.get("slug") or "")): item.get("view")
        for item in cached_views or []
        if isinstance(item, Mapping) and isinstance(item.get("view"), Mapping)
    }
    targets = {
        (
            str(rows[action_id].get("platform") or ""),
            str(rows[action_id].get("slug") or ""),
        )
        for action_id in ids
    }
    if not cached_by_target or targets - set(cached_by_target):
        raise ValueError("cached target view is required for execution")
    for platform, slug in targets:
        view_raw = cached_by_target.get((platform, slug))
        if not isinstance(view_raw, Mapping):
            raise ValueError("cached target view is required for execution")
        view = view_raw
        if current_configuration_revision(data_dir, environ, platform, slug) != str(
            view.get("config_revision") or ""
        ):
            raise ConfigError("configuration changed since the selected plan was published")
        _loc, series = locate_series(data_dir, platform, slug)
        if series is None:
            raise ConfigError("selected series is no longer configured")

    from dataclasses import replace

    from yt_dlp_emby.config import resolve_settings
    from yt_dlp_emby.dropout import run_dropout
    from yt_dlp_emby.dropout_manifest import filter_dropout_manifest
    from yt_dlp_emby.events import OperationContext, use_operation_context
    from yt_dlp_emby.pipeline import run_youtube_manifest
    from yt_dlp_emby.server.series import (
        _dropout_manifest_parsed,
        _load_root_yaml,
    )
    from yt_dlp_emby.youtube_manifest import parse_youtube_manifest

    callback = (
        operation_context.get("emit") or operation_context.get("progress_callback")
        if isinstance(operation_context, Mapping)
        else getattr(operation_context, "emit", None)
    )
    selected_action_descriptors = {
        (
            str(rows[action_id].get("platform") or action_id.split("|", 1)[0]),
            str(rows[action_id].get("slug") or ""),
            str(rows[action_id].get("provider_identity") or ""),
            str(rows[action_id].get("action") or ""),
        )
        for action_id in ids
    }
    operation = OperationContext(
        selected_actions=selected_action_descriptors,
        selected_action_specs={
            (
                str(rows[action_id].get("platform") or ""),
                str(rows[action_id].get("slug") or ""),
                str(rows[action_id].get("provider_identity") or ""),
                str(rows[action_id].get("action") or ""),
            ): rows[action_id]
            for action_id in ids
        },
        emit_callback=callback,
    )
    outcomes: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str], list[str]] = {}
    for action_id in ids:
        row = rows[action_id]
        platform = str(row.get("platform") or action_id.split("|", 1)[0])
        slug = str(row.get("slug") or action_id.split("|")[1])
        grouped.setdefault((platform, slug), []).append(action_id)
    with use_operation_context(operation):
        for (platform, slug), selected_ids in grouped.items():
            if platform == "dropout":
                manifest = _dropout_manifest_parsed(data_dir)
                _loc, series = locate_series(data_dir, platform, slug)
                manifest = filter_dropout_manifest(manifest, series_names=[series.name])
                settings = resolve_settings(
                    environ=environ,
                    cwd=data_dir,
                    manifest_library=str(manifest.library) if manifest.library else None,
                    manifest_old_dir=str(manifest.old_dir) if manifest.old_dir else None,
                    manifest_staging=str(manifest.staging) if manifest.staging else None,
                )
                code = run_dropout(
                    manifest,
                    settings,
                    force=force,
                    create=create,
                    series_slug_overrides={series.name: slug},
                    persist_listing_cache=False,
                )
            elif platform == "youtube":
                data, path = _load_root_yaml(data_dir, platform)
                manifest = parse_youtube_manifest(data, path)
                _loc, series = locate_series(data_dir, platform, slug)
                if not isinstance(series, YoutubeSeries):
                    raise ValueError("selected YouTube series is invalid")
                manifest = replace(manifest, series=(series,))
                settings = resolve_settings(
                    environ=environ,
                    cwd=data_dir,
                    manifest_library=str(manifest.library) if manifest.library else None,
                    manifest_old_dir=str(manifest.old_dir) if manifest.old_dir else None,
                    manifest_staging=str(manifest.staging) if manifest.staging else None,
                )
                code = run_youtube_manifest(
                    manifest, settings, series_slug_overrides={series.name: slug}
                )
            else:
                raise ValueError("unknown platform in selected action")
            outcomes.append(
                {
                    "platform": platform,
                    "slug": slug,
                    "return_code": code,
                    "selected_ids": selected_ids,
                }
            )
            if code:
                raise RuntimeError(f"download failed for {platform}|{slug}")
    return {"plan_id": plan_id, "selected": list(ids), "results": outcomes, "ok": True}


def verify_completed_actions(
    data_dir: Path,
    environ: Mapping[str, str],
    selected_actions: Sequence[Mapping[str, Any]],
    cached_views: Sequence[Mapping[str, Any]],
) -> set[str]:
    """Verify retried completions against current files and provider index.

    A previous worker event alone cannot mark an action complete: a crash may
    have happened after the event but before the file/index commit. This helper
    only returns IDs that are still satisfied on disk.
    """
    views = {
        (str(item.get("platform") or ""), str(item.get("slug") or "")): item.get("view")
        for item in cached_views
        if isinstance(item.get("view"), Mapping)
    }
    snapshots: dict[tuple[str, str], LibrarySnapshot] = {}
    completed: set[str] = set()
    for row in selected_actions:
        action_id = str(row.get("id") or "")
        platform, slug = str(row.get("platform") or ""), str(row.get("slug") or "")
        key = (platform, slug)
        view = views.get(key)
        if not action_id or not isinstance(view, Mapping):
            continue
        try:
            if current_configuration_revision(data_dir, environ, platform, slug) != str(
                view.get("config_revision") or ""
            ):
                continue
            disk = snapshots.get(key)
            if disk is None:
                _loc, series = locate_series(data_dir, platform, slug)
                disk_raw = view.get("disk")
                expected_mount = (
                    str(disk_raw.get("mount_identity"))
                    if isinstance(disk_raw, Mapping) and disk_raw.get("mount_identity")
                    else None
                )
                disk = library_snapshot(
                    _resolved_library(data_dir, platform, environ),
                    series_folder_rel(series),
                    expected_mount_identity=expected_mount,
                )
                snapshots[key] = disk
            if disk.status != "ready":
                continue
        except (ConfigError, OSError, ValueError, KeyError):
            continue

        action = str(row.get("action") or "")
        season, episode = row.get("dest_season"), row.get("dest_episode")
        if not isinstance(season, int) or not isinstance(episode, int):
            continue
        slot = (season, episode)
        present = slot in set(disk.episodes or ())
        cached_disk = view.get("disk")
        prior_fingerprints = (
            cached_disk.get("episode_fingerprints", []) if isinstance(cached_disk, Mapping) else []
        )
        prior = {
            (int(item[0]), int(item[1])): (int(item[2]), int(item[3]))
            for item in prior_fingerprints
            if isinstance(item, list) and len(item) == 4
        }.get(slot)
        current = {
            (item[0], item[1]): (item[2], item[3]) for item in disk.episode_fingerprints or ()
        }.get(slot)
        if action == "download":
            satisfied = present and prior is None
        elif action == "replace":
            satisfied = present and prior is not None and current != prior
        elif action == "rename":
            new_basename = str(row.get("new_basename") or "")
            satisfied = (
                present
                and bool(new_basename)
                and _provider_basename(disk.provider_index, str(row.get("provider_identity") or ""))
                == new_basename
            )
        elif action == "remove":
            satisfied = not _provider_has_identity(
                disk.provider_index, str(row.get("provider_identity") or "")
            )
        else:
            satisfied = False
        if satisfied:
            completed.add(action_id)
    return completed


def refresh_cached_disk_views(
    data_dir: Path,
    environ: Mapping[str, str],
    cached_views: Sequence[Mapping[str, Any]],
    *,
    force: bool = False,
    create: bool = False,
) -> list[dict[str, Any]]:
    """Rescan accepted targets for retry admission and rebuild their plans.

    This is an explicit POST/retry helper. It never creates library paths and
    returns refreshed views in the same `{platform, slug, view, plan}` shape
    consumed by the coordinator; the GET path continues to use its cache.
    """
    refreshed: list[dict[str, Any]] = []
    for item in cached_views:
        platform, slug = str(item.get("platform") or ""), str(item.get("slug") or "")
        view_raw = item.get("view")
        if not isinstance(view_raw, Mapping):
            raise ValueError("cached target view is required")
        if current_configuration_revision(data_dir, environ, platform, slug) != str(
            view_raw.get("config_revision") or ""
        ):
            raise ConfigError("configuration changed since the selected plan was published")
        _loc, series = locate_series(data_dir, platform, slug)
        disk_raw = view_raw.get("disk")
        expected_mount = (
            str(disk_raw.get("mount_identity"))
            if isinstance(disk_raw, Mapping) and disk_raw.get("mount_identity")
            else None
        )
        disk = library_snapshot(
            _resolved_library(data_dir, platform, environ),
            series_folder_rel(series),
            expected_mount_identity=expected_mount,
        )
        if disk.status != "ready":
            raise ConfigError(disk.error or "library unavailable")
        view = dict(view_raw)
        view["disk"] = disk.to_dict()
        plan = plan_variant(view, force=force, create=create)
        view["plan_id"] = plan["plan_id"]
        refreshed.append({"platform": platform, "slug": slug, "view": view, "plan": plan})
    return refreshed


def _provider_basename(index: Mapping[str, Any] | None, identity: str) -> str | None:
    for playlist in ((index or {}).get("playlists") or {}).values():
        if not isinstance(playlist, Mapping):
            continue
        episodes = playlist.get("episodes")
        record = episodes.get(identity) if isinstance(episodes, Mapping) else None
        if isinstance(record, Mapping):
            basename = record.get("basename")
            return str(basename) if basename else None
    return None


def _provider_has_identity(index: Mapping[str, Any] | None, identity: str) -> bool:
    return _provider_basename(index, identity) is not None


def check_target(
    data_dir: Path, environ: Mapping[str, str], target: Mapping[str, Any], emit: Emit | None = None
) -> dict[str, Any]:
    platform, slug = str(target.get("platform") or ""), str(target.get("slug") or "")
    if platform != "dropout":
        raise ValueError("Sonarr Check is only supported for Dropout")
    from yt_dlp_emby.dropout_check import check_series_report
    from yt_dlp_emby.server.series import _dropout_series_for_web_slug

    manifest, series = _dropout_series_for_web_slug(data_dir, slug)
    from yt_dlp_emby.config import resolve_settings

    settings = resolve_settings(
        environ=environ,
        cwd=data_dir,
        manifest_library=str(manifest.library) if manifest.library else None,
        manifest_old_dir=str(manifest.old_dir) if manifest.old_dir else None,
        manifest_staging=str(manifest.staging) if manifest.staging else None,
        require_ffmpeg=False,
        auto_cookies=False,
    )
    cached_view = target.get("cached_view")
    cached_provider_listings = (
        [row for row in cached_view.get("provider_listings", []) if isinstance(row, Mapping)]
        if isinstance(cached_view, Mapping)
        and isinstance(cached_view.get("provider_listings"), list)
        else None
    )
    return check_series_report(
        manifest,
        settings,
        slug,
        series=series,
        cached_provider_listings=cached_provider_listings,
    )


def diagnostics(
    data_dir: Path, environ: Mapping[str, str], checks: Sequence[str] = (), emit: Emit | None = None
) -> dict[str, Any]:
    from yt_dlp_emby.server.diagnostics import diagnostics as run_diagnostics

    return run_diagnostics(data_dir, environ, checks, emit=emit)
