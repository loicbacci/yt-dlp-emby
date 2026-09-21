"""Per-series last-refresh timestamps for the web UI."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from yt_dlp_emby.cache import atomic_write_text, file_lock

REFRESH_NAME = "refresh.json"
PARTS = ("listings", "disk", "sonarr")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def refresh_stamp_path(data_dir: Path) -> Path:
    return data_dir / "cache" / REFRESH_NAME


def series_refresh_key(platform: str, slug: str) -> str:
    return f"{platform}|{slug}"


def load_refresh_stamps(data_dir: Path) -> dict[str, Any]:
    path = refresh_stamp_path(data_dir)
    if not path.is_file():
        return {"series": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"series": {}}
    if not isinstance(data, dict):
        return {"series": {}}
    series = data.get("series")
    if not isinstance(series, dict):
        data["series"] = {}
    return data


def stamp_series_refresh(
    data_dir: Path,
    platform: str,
    slug: str,
    *parts: str,
    when: str | None = None,
) -> dict[str, str | None]:
    stamp = when or _utc_now()
    path = refresh_stamp_path(data_dir)
    with file_lock(path):
        data = load_refresh_stamps(data_dir)
        series = data.setdefault("series", {})
        key = series_refresh_key(platform, slug)
        row = series.get(key)
        if not isinstance(row, dict):
            row = {}
        for part in parts:
            if part in PARTS:
                row[part] = stamp
        series[key] = row
        atomic_write_text(path, json.dumps(data, indent=2))
    return series_refresh_payload(data_dir, platform, slug)


def series_refresh_payload(data_dir: Path, platform: str, slug: str) -> dict[str, str | None]:
    data = load_refresh_stamps(data_dir)
    row = data.get("series", {}).get(series_refresh_key(platform, slug))
    if not isinstance(row, dict):
        row = {}
    return {part: row.get(part) if isinstance(row.get(part), str) else None for part in PARTS}
