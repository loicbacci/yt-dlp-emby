"""Simple stdout/stderr logging with flush so progress is visible immediately."""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Mapping

from yt_dlp_emby.progress import format_size_estimate
from yt_dlp_emby.style import (
    ANSI_RE,
    RESET,
    bold,
    dim,
    green,
    pad_visible,
    red,
    visible_len,
    yellow,
)

_ACTION_STYLE = {
    "download": green,
    "add": green,
    "skip": dim,
    "refresh": dim,
    "unmapped": yellow,
    "replace": yellow,
    "rename": yellow,
    "remove": red,
}

_PLAN_STYLE = {
    "add": green,
    "replace": yellow,
    "rename": yellow,
    "refresh": dim,
    "remove": red,
}


_TERMINAL_COLS: int | None = None
_TERMINAL_COLS_AT = 0.0
_TERMINAL_TTL = 1.0


def _terminal_columns() -> int | None:
    global _TERMINAL_COLS, _TERMINAL_COLS_AT
    now = time.monotonic()
    if _TERMINAL_COLS is not None and now - _TERMINAL_COLS_AT < _TERMINAL_TTL:
        return _TERMINAL_COLS or None
    try:
        _TERMINAL_COLS = shutil.get_terminal_size().columns
    except OSError:
        _TERMINAL_COLS = 0
    _TERMINAL_COLS_AT = now
    return _TERMINAL_COLS or None


def info(message: str) -> None:
    print(fit_line(message, sys.stdout), flush=True)


def warn(message: str) -> None:
    prefix = yellow("warning:", stream=sys.stderr)
    print(f"{prefix} {fit_line(message, sys.stderr)}", file=sys.stderr, flush=True)


def error(message: str) -> None:
    prefix = red("error:", stream=sys.stderr)
    print(f"{prefix} {fit_line(message, sys.stderr)}", file=sys.stderr, flush=True)


def fit_line(text: str, stream: object | None = None) -> str:
    stream = stream if stream is not None else sys.stdout
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return text
    try:
        if not isatty():
            return text
        cols = _terminal_columns()
        if cols is None:
            return text
    except OSError:
        return text
    if cols < 8 or visible_len(text) <= cols:
        return text
    budget = cols - 1
    out: list[str] = []
    shown = 0
    index = 0
    while index < len(text) and shown < budget:
        ansi = ANSI_RE.match(text, index)
        if ansi:
            out.append(ansi.group(0))
            index = ansi.end()
            continue
        out.append(text[index])
        shown += 1
        index += 1
    ellipsis = "…"
    if "\033[" in text:
        ellipsis += RESET
    return "".join(out) + ellipsis


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return ""
    total = max(0, int(seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes:02d}m"
    if minutes:
        return f"{minutes}m{secs:02d}s"
    return f"{secs}s"


def format_elapsed(seconds: float) -> str:
    elapsed = max(0.0, seconds)
    if elapsed < 1:
        return f"{int(elapsed * 1000)}ms"
    if elapsed < 10:
        return f"{elapsed:.1f}s"
    return f"{int(elapsed)}s"


def format_dry_run_row(
    action: str,
    code: str,
    title: str,
    folder: str,
    origin: str | None = None,
    size: int | None = None,
) -> str:
    short = title if len(title) <= 40 else f"{title[:37]}..."
    styled = _ACTION_STYLE.get(action, lambda text: text)(action)
    line = f"{pad_visible(styled, 8)}  {code}  {short:<40}"
    if folder:
        line += f"  {folder}"
    hint = format_size_estimate(size)
    if hint:
        line += f"  {dim(hint)}"
    if origin:
        line += f"  {dim(f'({origin})')}"
    return line


def format_run_summary(
    *,
    downloaded: int = 0,
    skipped: int = 0,
    failed: int = 0,
    dry_run: bool = False,
    elapsed: float | None = None,
    remaining: int | None = None,
    interrupted: bool = False,
) -> str:
    clock = f"  {format_duration(elapsed)}" if elapsed is not None else ""
    done = bold("Done")
    if interrupted:
        extra = f"  remaining={remaining}" if remaining is not None else ""
        failed_part = red(f"failed={failed}") if failed else f"failed={failed}"
        return (
            f"{done}  {yellow('interrupted')}  downloaded={downloaded}  skipped={skipped}  "
            f"{failed_part}{extra}{clock}"
        )
    if dry_run:
        download_part = (
            green(f"download={downloaded}") if downloaded else dim(f"download={downloaded}")
        )
        return f"{done}  {dim('dry-run')}  {download_part}  {dim(f'skip={skipped}')}{clock}"
    failed_part = red(f"failed={failed}") if failed else f"failed={failed}"
    return f"{done}  downloaded={downloaded}  skipped={skipped}  {failed_part}{clock}"


def format_plan_counts(counts: dict[str, int], *, empty: str = "nothing to do") -> str:
    order = ("add", "replace", "rename", "refresh", "remove")
    parts = [
        _PLAN_STYLE.get(key, lambda text: text)(f"{counts[key]} {key}")
        for key in order
        if counts.get(key)
    ]
    extra = [f"{n} {key}" for key, n in counts.items() if key not in order and n]
    parts.extend(extra)
    return "  ".join(parts) if parts else empty


_UNIT_EXTRA_ORDER = (
    "replace",
    "rename",
    "remove",
    "unmapped",
    "omitted",
    "title differs",
)
_UNIT_EXTRA_STYLE = {
    "replace": yellow,
    "rename": yellow,
    "remove": red,
    "unmapped": red,
    "omitted": dim,
    "title differs": yellow,
}


def format_unit_plan(
    label: str,
    *,
    dest: str | None = None,
    skip: int = 0,
    download: int = 0,
    extras: Mapping[str, int] | None = None,
    listing_source: str | None = None,
    listing_seconds: float | None = None,
    disk_seconds: float | None = None,
    debug: bool = False,
    download_bytes: int | None = None,
) -> str:
    skip_part = dim(f"{skip} skip")
    download_part = green(f"{download} download") if download else dim(f"{download} download")
    hint = format_size_estimate(download_bytes)
    if hint and download:
        download_part += f" {dim(hint)}"
    line = f"  {label}"
    if dest:
        line += f" → {dest}"
    line += f"  {skip_part}  {download_part}"
    extra_counts = dict(extras or {})
    for key in _UNIT_EXTRA_ORDER:
        count = extra_counts.pop(key, 0)
        if not count:
            continue
        style = _UNIT_EXTRA_STYLE.get(key, lambda text: text)
        line += f"  {style(f'{count} {key}')}"
    for key, count in extra_counts.items():
        if count:
            line += f"  {count} {key}"
    if listing_source is not None and listing_seconds is not None:
        disk = disk_seconds or 0.0
        if debug:
            suffix = (
                f"{listing_source} {format_elapsed(listing_seconds)}  disk {format_elapsed(disk)}"
            )
        else:
            suffix = f"{listing_source}  {format_elapsed(listing_seconds + disk)}"
        line += f"  {dim(suffix)}"
    return line


@dataclass
class RunStats:
    started: float = field(default_factory=time.monotonic)
    downloaded: int = 0
    skipped: int = 0
    failed: int = 0
    filtered: int = 0
    remaining: int | None = None
    interrupted: bool = False
    dry_run: bool = False
    failures: list[tuple[str, str]] = field(default_factory=list)
    durations: list[float] = field(default_factory=list)

    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def mark_download(self, seconds: float) -> None:
        if seconds >= 0:
            self.durations.append(seconds)
            self.durations = self.durations[-5:]

    def eta(self, remaining: int) -> str | None:
        if remaining <= 0 or not self.durations:
            return None
        ordered = sorted(self.durations)
        mid = len(ordered) // 2
        if len(ordered) % 2:
            avg = ordered[mid]
        else:
            avg = (ordered[mid - 1] + ordered[mid]) / 2
        return format_duration(avg * remaining)

    def summary(self) -> str:
        return format_run_summary(
            downloaded=self.downloaded,
            skipped=self.skipped,
            failed=self.failed,
            dry_run=self.dry_run,
            elapsed=self.elapsed(),
            remaining=self.remaining,
            interrupted=self.interrupted,
        )

    def recap(self) -> None:
        if not self.failures:
            return
        shown = self.failures[:20]
        error("failed episodes:")
        for stem, message in shown:
            error(f"  {stem}: {message}")
        extra = len(self.failures) - len(shown)
        if extra:
            error(f"  … and {extra} more")
