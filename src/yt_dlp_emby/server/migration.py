"""One-time retirement of disposable state from the public CLI/run manager."""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from yt_dlp_emby.cache import atomic_write_private

LEGACY_FILES = ("events.jsonl", "download-only.json", "cache/refresh.json")


def archive_legacy_state(data_dir: Path) -> None:
    """Run under the coordinator lock; preserve canonical files and all media."""
    root = data_dir.resolve()
    archive = root / "legacy-state"
    marker = archive / "migration.json"
    if archive.is_symlink():
        raise ValueError("legacy-state directory cannot be a symlink")
    if marker.exists():
        return
    archive.mkdir(mode=0o700, exist_ok=True)
    for listed in LEGACY_FILES:
        source = root / listed
        if not source.parent.resolve().is_relative_to(root):
            continue
        try:
            mode = source.lstat().st_mode
        except FileNotFoundError:
            continue
        if not stat.S_ISREG(mode):
            continue
        target = archive / listed.replace("/", "-")
        # A previous incomplete startup may already have archived another copy.
        suffix = 0
        while target.exists() or target.is_symlink():
            suffix += 1
            target = archive / f"{listed.replace('/', '-')}.{suffix}"
        os.replace(source, target)
        target.chmod(0o600)
    atomic_write_private(marker, json.dumps({"version": 1, "archived": list(LEGACY_FILES)}))
