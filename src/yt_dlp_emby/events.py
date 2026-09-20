"""Structured run events for the web UI (JSONL sidecar)."""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from yt_dlp_emby.config import ConfigError

_EVENTS_PATH: Path | None = None
_ONLY_IDS: set[str] | None = None
_CURRENT_ITEM_ID: str | None = None
_PROGRESS_MIN_INTERVAL = 0.25
_last_progress_at = 0.0


def reset_runtime() -> None:
    global _EVENTS_PATH, _ONLY_IDS, _CURRENT_ITEM_ID, _last_progress_at
    _EVENTS_PATH = None
    _ONLY_IDS = None
    _CURRENT_ITEM_ID = None
    _last_progress_at = 0.0


def set_current_item_id(value: str | None) -> None:
    global _CURRENT_ITEM_ID
    _CURRENT_ITEM_ID = value


def current_item_id() -> str | None:
    return _CURRENT_ITEM_ID


def read_events_path(environ: Mapping[str, str] | None = None) -> Path | None:
    global _EVENTS_PATH, _ONLY_IDS
    env = environ or os.environ
    raw = env.get("YT_DLP_EMBY_EVENTS")
    _EVENTS_PATH = Path(raw) if raw else None
    only_raw = env.get("YT_DLP_EMBY_ONLY")
    _ONLY_IDS = None
    if only_raw:
        data = json.loads(Path(only_raw).read_text(encoding="utf-8"))
        ids = data.get("ids")
        if not isinstance(ids, list):
            raise ConfigError("YT_DLP_EMBY_ONLY ids must be a list")
        if not ids:
            raise ConfigError("empty download selection")
        _ONLY_IDS = {str(item) for item in ids}
    return _EVENTS_PATH


def item_id(platform: str, slug: str, code: str) -> str:
    return f"{platform}|{slug}|{code}"


def allowed_item_id(item_id_value: str) -> bool:
    if _ONLY_IDS is None:
        return True
    return item_id_value in _ONLY_IDS


def emit(payload: dict[str, Any]) -> None:
    if _EVENTS_PATH is None:
        return
    _EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _EVENTS_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, separators=(",", ":")) + "\n")


def emit_progress(payload: dict[str, Any], *, force: bool = False) -> None:
    global _last_progress_at
    now = time.monotonic()
    if not force and now - _last_progress_at < _PROGRESS_MIN_INTERVAL:
        return
    _last_progress_at = now
    emit(payload)


def merge_plan_source(
    plan_path: Path,
    platform: str,
    source_payload: dict[str, Any],
    *,
    force: bool,
) -> None:
    if plan_path.is_file():
        data = json.loads(plan_path.read_text(encoding="utf-8"))
    else:
        data = {"generated_at": None, "force": force, "sources": {}}
    data["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data["force"] = bool(data.get("force")) or force
    sources = data.setdefault("sources", {})
    sources[platform] = source_payload
    plan_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = plan_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(plan_path)


def parse_events_file(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        out.append(json.loads(line))
    return out


def folder_label(dest_season: int) -> str:
    return "Specials" if dest_season == 0 else f"Season {dest_season}"


def season_title_for_dest(season: Any, dest: int) -> str | None:
    to_season = season.to_season if season.to_season is not None else season.dropout
    if to_season == dest:
        title = getattr(season, "title", None)
        return title if title else None
    return None


def emit_dropout_unit(
    *,
    series_name: str,
    slug: str,
    season: Any,
    work_rows: list[Any],
    skip: int,
    download: int,
    unmapped: int,
    replace: int,
) -> None:
    dests: dict[int, dict[str, int]] = {}
    for row in work_rows:
        dest = row.dest_season
        if dest is None:
            continue
        bucket = dests.setdefault(
            int(dest),
            {"download": 0, "skip": 0, "unmapped": 0, "replace": 0},
        )
        action = row.action
        if action in bucket:
            bucket[action] += 1
    for dest, counts in sorted(dests.items(), key=lambda item: (item[0] == 0, item[0])):
        stitle = season_title_for_dest(season, dest)
        emit(
            {
                "event": "season",
                "platform": "dropout",
                "slug": slug,
                "series": series_name,
                "dest_season": dest,
                "season_title": stitle,
                "folder": folder_label(dest),
                "download": counts.get("download", 0),
                "skip": counts.get("skip", 0),
                "unmapped": counts.get("unmapped", 0),
                "replace": counts.get("replace", 0),
            }
        )
    if not dests and (skip or download or unmapped):
        dest = season.to_season if season.to_season is not None else (season.dropout or 0)
        emit(
            {
                "event": "season",
                "platform": "dropout",
                "slug": slug,
                "series": series_name,
                "dest_season": int(dest),
                "season_title": getattr(season, "title", None),
                "folder": folder_label(int(dest)),
                "download": download,
                "skip": skip,
                "unmapped": unmapped,
                "replace": replace,
            }
        )
    for row in work_rows:
        if row.action == "skip":
            continue
        if row.action not in {"download", "unmapped", "replace", "add"}:
            continue
        dest = row.dest_season if row.dest_season is not None else 0
        action = "download" if row.action == "add" else row.action
        emit(
            {
                "event": "item",
                "id": item_id("dropout", slug, row.code),
                "action": action,
                "code": row.code,
                "title": row.title,
                "dest_season": dest,
                "season_title": season_title_for_dest(season, dest),
                "folder": folder_label(dest),
                "size": row.size,
                "series": series_name,
                "slug": slug,
                "platform": "dropout",
            }
        )


def plan_from_events(
    events: list[dict[str, Any]], platform: str | None = None
) -> dict[str, Any]:
    seasons: list[dict[str, Any]] = []
    items: list[dict[str, Any]] = []
    for row in events:
        kind = row.get("event")
        if kind not in {"season", "item"}:
            continue
        if platform and row.get("platform") not in {None, platform}:
            continue
        payload = {k: v for k, v in row.items() if k != "event"}
        if kind == "season":
            seasons.append(payload)
        else:
            items.append(payload)
    return {"ok": True, "error": None, "seasons": seasons, "items": items}
