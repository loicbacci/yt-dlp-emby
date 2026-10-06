"""Context-local execution selection and structured worker callbacks."""

from __future__ import annotations

import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from typing import Any, Iterator, Mapping

from yt_dlp_emby.config import ConfigError

_PROGRESS_MIN_INTERVAL = 0.25
_OPERATION_CONTEXT: ContextVar[OperationContext | None] = ContextVar(
    "yt_dlp_emby_operation_context", default=None
)


@dataclass
class OperationContext:
    """Selection and callbacks belong to one explicitly admitted operation."""

    selected_ids: set[str] | None = None
    selected_actions: set[tuple[str, str, str, str]] | None = None
    selected_action_specs: dict[tuple[str, str, str, str], Mapping[str, Any]] | None = None
    emit_callback: Any = None
    current_item_id: str | None = None
    cancellation: Any = None
    logger: Any = None
    progress_callback: Any = None
    last_progress_at: float = 0.0


@contextmanager
def use_operation_context(context: OperationContext) -> Iterator[OperationContext]:
    token = _OPERATION_CONTEXT.set(context)
    try:
        yield context
    finally:
        _OPERATION_CONTEXT.reset(token)


@contextmanager
def capture_events() -> Iterator[list[dict[str, Any]]]:
    """Capture callbacks in an isolated context, primarily for service tests."""
    sink: list[dict[str, Any]] = []
    previous = _OPERATION_CONTEXT.get()
    context = (
        replace(previous, emit_callback=sink.append)
        if previous
        else OperationContext(emit_callback=sink.append)
    )
    with use_operation_context(context):
        yield sink


def set_current_item_id(value: str | None) -> None:
    context = _OPERATION_CONTEXT.get()
    if context is not None:
        context.current_item_id = value


def current_item_id() -> str | None:
    context = _OPERATION_CONTEXT.get()
    return context.current_item_id if context is not None else None


def selection_is_active() -> bool:
    """True only for web/admitted jobs with an explicit action set."""
    context = _OPERATION_CONTEXT.get()
    return context is not None and context.selected_actions is not None


def item_id(platform: str, slug: str, code: str) -> str:
    return f"{platform}|{slug}|{code}"


def allowed_item_id(item_id_value: str) -> bool:
    context = _OPERATION_CONTEXT.get()
    return context is None or context.selected_ids is None or item_id_value in context.selected_ids


def allowed_provider_action(
    platform: str, slug: str, provider_identity: str, action: str, fallback_id: str
) -> bool:
    context = _OPERATION_CONTEXT.get()
    if context is not None and context.selected_actions is not None:
        return (platform, slug, provider_identity, action) in context.selected_actions
    return allowed_item_id(fallback_id)


def explicitly_selected_provider_action(
    platform: str, slug: str, provider_identity: str, action: str
) -> bool:
    context = _OPERATION_CONTEXT.get()
    return bool(
        context is not None
        and context.selected_actions is not None
        and (platform, slug, provider_identity, action) in context.selected_actions
    )


def validate_selected_action(
    platform: str, slug: str, provider_identity: str, action: str, actual: Mapping[str, Any]
) -> bool:
    """Reject live actions whose meaning differs from the admitted selection."""
    context = _OPERATION_CONTEXT.get()
    key = (platform, slug, provider_identity, action)
    if context is None:
        return True
    if context.selected_actions is not None and key not in context.selected_actions:
        return False
    if context.selected_action_specs is None:
        return True
    expected = context.selected_action_specs.get(key)
    if expected is None:
        raise ConfigError("PLAN_STALE: selected action has no admission specification")
    for field in ("dest_season", "dest_episode", "title", "url", "old_basename", "new_basename"):
        if field in expected and expected[field] != actual.get(field):
            raise ConfigError("PLAN_STALE: selected action changed before execution")
    return True


def assert_selected_actions_seen(
    seen_keys: set[tuple[str, str, str, str]],
    *,
    platform: str | None = None,
    slug: str | None = None,
) -> None:
    """Fail closed if fresh planning omits an admitted action in this scope."""
    context = _OPERATION_CONTEXT.get()
    if context is None or context.selected_actions is None:
        return
    scoped = {
        key
        for key in context.selected_actions
        if (platform is None or key[0] == platform) and (slug is None or key[1] == slug)
    }
    missing = scoped - seen_keys
    if missing:
        raise ConfigError("PLAN_STALE: selected provider action is no longer available")


def emit(payload: dict[str, Any]) -> None:
    context = _OPERATION_CONTEXT.get()
    if context is None:
        return
    if context.emit_callback is not None:
        context.emit_callback(dict(payload))
    if context.progress_callback is not None and payload.get("event") in {
        "progress",
        "item",
        "episode_progress",
        "download_progress",
    }:
        context.progress_callback(dict(payload))


def emit_progress(payload: dict[str, Any], *, force: bool = False) -> None:
    context = _OPERATION_CONTEXT.get()
    if context is None:
        return
    now = time.monotonic()
    if not force and now - context.last_progress_at < _PROGRESS_MIN_INTERVAL:
        return
    context.last_progress_at = now
    emit(payload)


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
