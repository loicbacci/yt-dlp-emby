"""Shared run UI: series headers, compact unit plans, work rows, finish."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from yt_dlp_emby.config import Settings
from yt_dlp_emby.log import RunStats, format_dry_run_row, info, warn
from yt_dlp_emby.style import bold, yellow

# Already on disk (or equivalent): only with -v.
_VERBOSE_ACTIONS = {"skip", "refresh"}
# Progress bars cover these; print the row on dry-run only.
_DOWNLOAD_ACTIONS = {"download", "add", "replace"}


@dataclass(frozen=True)
class WorkRow:
    action: str
    code: str
    title: str
    folder: str
    note: str | None = None


def log_step(settings: Settings, message: str) -> None:
    if settings.show_steps:
        info(message)


def note(settings: Settings, message: str) -> None:
    if settings.show_summary:
        info(message)


def warn_if(settings: Settings, message: str) -> None:
    if settings.show_warnings:
        warn(message)


def finish(settings: Settings, stats: RunStats) -> int:
    if settings.show_summary:
        stats.recap()
        info("")
        info(stats.summary())
    if stats.interrupted:
        return 130
    return 1 if stats.failed else 0


def note_series(settings: Settings, name: str, last_series: str | None) -> str:
    if last_series != name:
        if last_series is not None:
            note(settings, "")
        note(settings, bold(name))
    return name


def print_work_rows(
    settings: Settings,
    rows: Sequence[WorkRow],
    *,
    indent: str = "    ",
) -> None:
    for row in rows:
        if row.action in _VERBOSE_ACTIONS and not settings.verbose:
            continue
        if row.action in _DOWNLOAD_ACTIONS and not settings.dry_run:
            continue
        note(
            settings,
            indent + format_dry_run_row(row.action, row.code, row.title, row.folder),
        )
        if row.note and settings.verbose:
            note(settings, "              " + yellow(row.note))
