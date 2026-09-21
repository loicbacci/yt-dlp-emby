"""Structured run events for the web UI (JSONL sidecar)."""

from __future__ import annotations

import json
import os
import re
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping

from yt_dlp_emby.config import ConfigError

# Must match ITEM_ID_PATTERN in server/runner.py (kept local so the CLI
# doesn't import server dependencies). Child-side re-validation of ONLY ids.
_ONLY_ID_RE = re.compile(r"^(youtube|dropout)\|[^|]{1,128}(\|[^|]{1,256})?$")

_EVENTS_PATH: Path | None = None
_ONLY_IDS: set[str] | None = None
_CURRENT_ITEM_ID: str | None = None
_EVENT_SINK: list[dict[str, Any]] | None = None
_PROGRESS_MIN_INTERVAL = 0.25
_last_progress_at = 0.0


def reset_runtime() -> None:
    global _EVENTS_PATH, _ONLY_IDS, _CURRENT_ITEM_ID, _EVENT_SINK, _last_progress_at
    _EVENTS_PATH = None
    _ONLY_IDS = None
    _CURRENT_ITEM_ID = None
    _EVENT_SINK = None
    _last_progress_at = 0.0


@contextmanager
def capture_events() -> Iterator[list[dict[str, Any]]]:
    global _EVENT_SINK
    sink: list[dict[str, Any]] = []
    previous = _EVENT_SINK
    _EVENT_SINK = sink
    try:
        yield sink
    finally:
        _EVENT_SINK = previous


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
    if _EVENTS_PATH is not None:
        _EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    only_raw = env.get("YT_DLP_EMBY_ONLY")
    _ONLY_IDS = None
    if only_raw:
        data = json.loads(Path(only_raw).read_text(encoding="utf-8"))
        ids = data.get("ids")
        if not isinstance(ids, list):
            raise ConfigError("YT_DLP_EMBY_ONLY ids must be a list")
        if not ids:
            raise ConfigError("empty download selection")
        for item in ids:
            if not _ONLY_ID_RE.match(str(item)):
                raise ConfigError(f"invalid download selection id: {item!r}")
        _ONLY_IDS = {str(item) for item in ids}
    return _EVENTS_PATH


def item_id(platform: str, slug: str, code: str) -> str:
    return f"{platform}|{slug}|{code}"


def allowed_item_id(item_id_value: str) -> bool:
    if _ONLY_IDS is None:
        return True
    return item_id_value in _ONLY_IDS


def emit(payload: dict[str, Any]) -> None:
    if _EVENT_SINK is not None:
        _EVENT_SINK.append(payload)
    if _EVENTS_PATH is None:
        return
    line = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(str(_EVENTS_PATH), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    try:
        os.write(fd, line)
    finally:
        os.close(fd)


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
    data: dict[str, Any]
    if plan_path.is_file():
        try:
            loaded = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = None
        data = (
            loaded
            if isinstance(loaded, dict)
            else {"generated_at": None, "force": force, "sources": {}}
        )
    else:
        data = {"generated_at": None, "force": force, "sources": {}}
    data["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    data["force"] = bool(data.get("force")) or force
    sources = data.setdefault("sources", {})
    sources[platform] = source_payload
    _write_plan(plan_path, data)


def _write_plan(plan_path: Path, data: dict[str, Any]) -> None:
    from yt_dlp_emby.cache import atomic_write_text, file_lock

    # 0644 is intentional: plan.json is UI-shared state readable by any local UID (secrets stay 0600).
    with file_lock(plan_path):
        atomic_write_text(plan_path, json.dumps(data, indent=2) + "\n", mode=0o644)


def merge_plan_slug(
    plan_path: Path,
    platform: str,
    slug: str,
    source_payload: dict[str, Any],
    *,
    aliases: set[str] | None = None,
    force: bool = False,
) -> None:
    """Replace one series' seasons/items inside a platform block."""
    wanted = {slug, *(aliases or set())} - {""}
    if plan_path.is_file():
        try:
            loaded = json.loads(plan_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            loaded = None
        data = (
            loaded
            if isinstance(loaded, dict)
            else {"generated_at": None, "force": force, "sources": {}}
        )
    else:
        data = {"generated_at": None, "force": force, "sources": {}}
    data["generated_at"] = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    if force:
        data["force"] = True
    else:
        data["force"] = bool(data.get("force"))
    sources = data.setdefault("sources", {})
    existing = sources.get(platform)
    if not isinstance(existing, dict):
        existing = {"ok": True, "error": None, "seasons": [], "items": []}
    seasons = [
        row
        for row in existing.get("seasons") or []
        if isinstance(row, dict) and row.get("slug") not in wanted
    ]
    items = [
        row
        for row in existing.get("items") or []
        if isinstance(row, dict) and row.get("slug") not in wanted
    ]
    for row in source_payload.get("seasons") or []:
        if isinstance(row, dict):
            seasons.append({**row, "slug": slug})
    for row in source_payload.get("items") or []:
        if isinstance(row, dict):
            patched = {**row, "slug": slug}
            item_id_value = patched.get("id")
            if isinstance(item_id_value, str):
                parts = item_id_value.split("|")
                if len(parts) >= 3:
                    patched["id"] = "|".join([parts[0], slug, *parts[2:]])
            items.append(patched)
    error = source_payload.get("error")
    sources[platform] = {
        "ok": False if error else bool(existing.get("ok", True)),
        "error": error if error else existing.get("error"),
        "seasons": seasons,
        "items": items,
    }
    _write_plan(plan_path, data)


def parse_events_file(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    bad = 0
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        if isinstance(payload, dict):
            out.append(payload)
        else:
            bad += 1
    if bad:
        from yt_dlp_emby.log import warn

        warn(f"skipped {bad} malformed event line(s) in {path}")
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
                "url": getattr(season, "url", None),
            }
        )


def plan_from_events(events: list[dict[str, Any]], platform: str | None = None) -> dict[str, Any]:
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
