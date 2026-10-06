"""Atomic, human-inspectable cache snapshots for provider catalogs and inventory."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping


def _path(data_dir: Path, platform: str, slug: str) -> Path:
    # Slugs originate in manifests but still pass through a strict filename map.
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in slug)[:200]
    suffix = hashlib.sha256(slug.encode("utf-8")).hexdigest()[:10]
    return data_dir / "cache" / platform / f"{safe}-{suffix}.json"


def write_snapshot(data_dir: Path, platform: str, slug: str, view: Mapping[str, Any]) -> None:
    """Persist provider listings and disk inventory with their input fingerprint."""
    target = _path(data_dir, platform, slug)
    target.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    try:
        os.chmod(target.parent, 0o700)
    except OSError:
        pass
    fingerprint_data = {
        "config_revision": view.get("config_revision"),
        "source_signature": view.get("source_signature"),
        "context_signature": view.get("context_signature"),
    }
    fingerprint = hashlib.sha256(
        json.dumps(fingerprint_data, sort_keys=True).encode("utf-8")
    ).hexdigest()
    snapshot = {
        "version": 1,
        "platform": platform,
        "slug": slug,
        "fingerprint": fingerprint,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "cache_times": view.get("cache_times", {}),
        "provider_listings": view.get("provider_listings", []),
        "disk": view.get("disk", {}),
        "sonarr": view.get("sonarr"),
        "view": dict(view),
    }
    fd, name = tempfile.mkstemp(prefix=f".{target.name}.", suffix=".tmp", dir=target.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(snapshot, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, target)
    finally:
        try:
            os.unlink(name)
        except FileNotFoundError:
            pass


def patch_inventory(data_dir: Path, platform: str, slug: str, season: int, episode: int) -> None:
    """Update a known successful download without rescanning the library."""
    target = _path(data_dir, platform, slug)
    try:
        snapshot = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("disk"), dict):
        return
    disk = snapshot["disk"]
    values = disk.get("episodes")
    if not isinstance(values, list):
        values = []
    pair = [int(season), int(episode)]
    if pair not in values:
        values.append(pair)
        values.sort()
    disk["episodes"] = values
    disk["series_exists"] = True
    disk["status"] = "ready"
    disk["scanned_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
    snapshot["fetched_at"] = disk["scanned_at"]
    view = snapshot.get("view")
    if isinstance(view, dict):
        view_disk = view.get("disk")
        if isinstance(view_disk, dict):
            view_disk.update(disk)
        times = view.setdefault("cache_times", {})
        if isinstance(times, dict):
            times["disk"] = disk["scanned_at"]
    root_times = snapshot.setdefault("cache_times", {})
    if isinstance(root_times, dict):
        root_times["disk"] = disk["scanned_at"]
    tmp = target.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")), encoding="utf-8"
    )
    os.replace(tmp, target)
