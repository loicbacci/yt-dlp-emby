"""Simple stdout/stderr logging with flush so progress is visible immediately."""

from __future__ import annotations

import shutil
import sys
import time
from dataclasses import dataclass, field
from typing import Mapping

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
        cols = shutil.get_terminal_size().columns
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


def format_dry_run_row(action: str, code: str, title: str, folder: str) -> str:
    short = title if len(title) <= 40 else f"{title[:37]}..."
    styled = _ACTION_STYLE.get(action, lambda text: text)(action)
    return f"{pad_visible(styled, 8)}  {code}  {short:<40}  {folder}"


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
) -> str:
    skip_part = dim(f"{skip} skip")
    download_part = (
        green(f"{download} download") if download else dim(f"{download} download")
    )
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
                f"{listing_source} {format_elapsed(listing_seconds)}  "
                f"disk {format_elapsed(disk)}"
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

    def eta(self, remaining: int) -> str | None:
        if remaining <= 0 or not self.durations:
            return None
        avg = sum(self.durations) / len(self.durations)
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
        error("failed episodes:")
        for stem, message in self.failures:
            error(f"  {stem}: {message}")
