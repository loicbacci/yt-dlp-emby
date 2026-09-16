"""A compact progress bar driven by yt-dlp hooks and log messages."""

from __future__ import annotations

import os
import re
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Any, TextIO

from yt_dlp_emby.events import current_item_id, emit_progress
from yt_dlp_emby.style import color_enabled, green, strip_ansi, visible_len

_ITEM = re.compile(r"Downloading item (\d+) of (\d+)")
_ITEM_UNKNOWN = re.compile(r"Downloading item (\d+) of ")
_SUB_EXTS = {".srt", ".vtt", ".ass", ".ttml"}
_COPY_BAR_MIN = 8 * 1024 * 1024


def parse_playlist_item(message: str) -> tuple[int, int | None] | None:
    clean = strip_ansi(message)
    match = _ITEM.search(clean)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = _ITEM_UNKNOWN.search(clean)
    if match:
        return int(match.group(1)), None
    return None


def stream_is_tty(stream: TextIO) -> bool:
    isatty = getattr(stream, "isatty", None)
    if not callable(isatty):
        return False
    try:
        return bool(isatty())
    except Exception:
        return False


def bar_width(stream: TextIO | None = None, fallback: int = 28) -> int:
    cols = 0
    if stream is not None:
        fileno = getattr(stream, "fileno", None)
        if callable(fileno):
            try:
                cols = os.get_terminal_size(fileno()).columns
            except Exception:
                cols = 0
    if cols <= 0:
        try:
            cols = shutil.get_terminal_size().columns
        except Exception:
            return fallback
    return max(10, min(40, cols - 52))


# Combined A/V around 5 Mbit/s for the default 1080p mkv selector.
ESTIMATE_BITS_PER_SECOND = 5_000_000


def format_bytes(num: float | None) -> str:
    if num is None:
        return "?"
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(value) < 1024.0 or unit == "GiB":
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}GiB"


def estimate_media_bytes(
    *,
    filesize: int | None = None,
    duration: float | None = None,
) -> int | None:
    """Prefer yt-dlp's size; otherwise estimate from duration at 1080p bitrate."""
    if isinstance(filesize, int) and filesize > 0:
        return filesize
    if duration is not None and duration > 0:
        return int(float(duration) * (ESTIMATE_BITS_PER_SECOND / 8.0))
    return None


def format_size_estimate(nbytes: int | None) -> str | None:
    if nbytes is None or nbytes <= 0:
        return None
    return f"~{format_bytes(nbytes)}"


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def render_bar(
    percent: float,
    width: int = 28,
    *,
    fancy: bool = False,
    color: bool = False,
) -> str:
    width = max(1, width)
    filled = int(round((percent / 100.0) * width))
    filled = min(width, max(0, filled))
    fill_ch, empty_ch = ("█", "░") if fancy else ("#", "-")
    fill = fill_ch * filled
    empty = empty_ch * (width - filled)
    if color and fill:
        fill = green(fill, enabled=True)
    return fill + empty


def stream_label(data: dict[str, Any]) -> str:
    info = data.get("info_dict") if isinstance(data.get("info_dict"), dict) else {}
    filename = str(data.get("filename") or info.get("filename") or "")
    suffix = Path(filename).suffix.lower()
    ext = str(info.get("ext") or "").lower()
    lang = str(info.get("language") or "").strip()
    if suffix in _SUB_EXTS or ext in {"srt", "vtt", "ass", "ttml"}:
        return f"{lang}.srt" if lang else "subtitles"
    vcodec = info.get("vcodec")
    acodec = info.get("acodec")
    has_video = vcodec not in (None, "none")
    has_audio = acodec not in (None, "none")
    if has_video and not has_audio:
        return "video"
    if has_audio and not has_video:
        return "audio"
    if has_video and has_audio:
        return "media"
    return "download"


def format_progress_line(
    data: dict[str, Any],
    width: int = 28,
    label: str | None = None,
    *,
    fancy: bool = False,
    color: bool = False,
) -> str:
    downloaded = data.get("downloaded_bytes") or 0
    total = data.get("total_bytes") or data.get("total_bytes_estimate")
    speed = data.get("speed")
    eta = data.get("eta")
    if total:
        percent = min(100.0, (downloaded / total) * 100.0)
        bar = render_bar(percent, width=width, fancy=fancy, color=color)
        body = (
            f"[{bar}] {percent:5.1f}%  "
            f"{format_bytes(downloaded)}/{format_bytes(total)}  "
            f"{format_bytes(speed)}/s  ETA {format_eta(eta)}"
        )
    else:
        body = f"{format_bytes(downloaded)}  {format_bytes(speed)}/s"
    if label:
        return f"{label}  {body}"
    return body


def format_copy_line(
    copied: int,
    total: int,
    width: int = 28,
    label: str = "copy",
    *,
    fancy: bool = False,
    color: bool = False,
) -> str:
    if total:
        percent = min(100.0, (copied / total) * 100.0)
        bar = render_bar(percent, width=width, fancy=fancy, color=color)
        return (
            f"{label}  [{bar}] {percent:5.1f}%  "
            f"{format_bytes(copied)}/{format_bytes(total)}"
        )
    return f"{label}  {format_bytes(copied)}"


def format_extract_line(
    current: int,
    total: int | None,
    width: int = 28,
    listing: str = "playlist",
    *,
    fancy: bool = False,
    color: bool = False,
) -> str:
    activity = f"Listing {listing}"
    if total:
        percent = min(100.0, (current / total) * 100.0)
        bar = render_bar(percent, width=width, fancy=fancy, color=color)
        return f"[{bar}] {current}/{total}  {activity}"
    return f"{current} videos  {activity}"


class ProgressDisplay:
    """Render a single updating line on stderr (live TTY) or throttled log lines."""

    def __init__(
        self,
        enabled: bool = True,
        stream: TextIO | None = None,
        *,
        live: bool | None = None,
        heartbeat: bool = False,
    ) -> None:
        self.enabled = enabled
        self.stream = stream if stream is not None else sys.stderr
        self.live = bool(enabled and (stream_is_tty(self.stream) if live is None else live))
        self.width = bar_width(self.stream) if self.live else 28
        self._last_len = 0
        self._last_text = ""
        self._last_log = 0.0
        self._open = False
        self._label = "Working…"
        self._started = time.monotonic()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if enabled and heartbeat and self.live:
            self._thread = threading.Thread(
                target=self._run_heartbeat, name="yt-dlp-emby-progress", daemon=True
            )
            self._thread.start()

    def _draw(self, text: str, *, force: bool = False) -> None:
        if not self.enabled:
            return
        if self.live:
            vis = visible_len(text)
            padded = text + " " * max(0, self._last_len - vis)
            self.stream.write("\r" + padded)
            self.stream.flush()
            self._last_len = vis
            self._open = True
            return
        now = time.monotonic()
        if not force and text == self._last_text and now - self._last_log < 1.0:
            return
        if not force and now - self._last_log < 1.0:
            return
        self.stream.write(text + "\n")
        self.stream.flush()
        self._last_text = text
        self._last_log = now
        self._open = False

    def finish(self, text: str | None = None) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        if not self.enabled:
            return
        if text:
            self._draw(text, force=True)
        if self.live and self._open:
            self.stream.write("\n")
            self.stream.flush()
        self._last_len = 0
        self._open = False

    def close(self) -> None:
        self.finish()

    def _bar_style(self) -> dict[str, bool]:
        return {
            "fancy": self.live,
            "color": self.live and color_enabled(self.stream),
        }

    def start_heartbeat(self, label: str) -> None:
        with self._lock:
            self._label = label
            self._started = time.monotonic()
            self._redraw_heartbeat_locked()
        if self.enabled and self.live and self._thread is None:
            self._stop = threading.Event()
            self._thread = threading.Thread(
                target=self._run_heartbeat, name="yt-dlp-emby-progress", daemon=True
            )
            self._thread.start()

    def stop_heartbeat(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
            self._thread = None
        self._stop = threading.Event()

    def _run_heartbeat(self) -> None:
        while not self._stop.wait(1.0):
            with self._lock:
                self._redraw_heartbeat_locked()

    def _heartbeat_line(self) -> str:
        elapsed = int(time.monotonic() - self._started)
        return f"{self._label}  ({elapsed}s)"

    def _redraw_heartbeat_locked(self) -> None:
        self._draw(self._heartbeat_line())


class DownloadProgress(ProgressDisplay):
    def hook(self, data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        status = data.get("status")
        if status == "downloading":
            self.stop_heartbeat()
            label = stream_label(data)
            self._draw(
                format_progress_line(
                    data, width=self.width, label=label, **self._bar_style()
                )
            )
            item = current_item_id()
            if item:
                total = data.get("total_bytes") or data.get("total_bytes_estimate")
                emit_progress(
                    {
                        "event": "progress",
                        "phase": label,
                        "id": item,
                        "percent": data.get("_percent_str"),
                        "speed": data.get("speed"),
                        "eta": data.get("eta"),
                        "bytes": data.get("downloaded_bytes"),
                        "total": total,
                    }
                )
        elif status == "finished":
            self._draw(f"{stream_label(data)}  complete")

    def postprocessor_hook(self, data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        name = str(data.get("postprocessor") or "")
        status = data.get("status")
        lowered = name.lower()
        if status == "started" and ("remux" in lowered or "merger" in lowered or "merge" in lowered):
            label = "remux" if "remux" in lowered else "merge"
            self.start_heartbeat(label)
        elif status == "started" and "subtitle" in lowered:
            self.start_heartbeat("subtitles")
        elif status == "finished" and ("remux" in lowered or "merger" in lowered or "merge" in lowered):
            self.stop_heartbeat()
            self._draw("remux  complete" if "remux" in lowered else "merge  complete")

    def copy_update(self, copied: int, total: int, label: str = "copy") -> None:
        self.stop_heartbeat()
        self._draw(
            format_copy_line(
                copied, total, width=self.width, label=label, **self._bar_style()
            )
        )


class ExtractProgress(ProgressDisplay):
    """Status/item progress with an elapsed-time heartbeat so long waits look alive."""

    def __init__(
        self,
        enabled: bool = True,
        stream: TextIO | None = None,
        *,
        heartbeat: bool = False,
        live: bool | None = None,
        listing: str = "playlist",
        site: str = "YouTube",
    ) -> None:
        self.listing = listing
        self.site = site
        self._current: int | None = None
        self._total: int | None = None
        super().__init__(enabled=enabled, stream=stream, live=live, heartbeat=heartbeat)
        self._label = f"Connecting to {site}…"

    def status(self, text: str) -> None:
        with self._lock:
            self._label = text
            self._redraw_locked()

    def item(self, current: int, total: int | None) -> None:
        with self._lock:
            self._current = current
            self._total = total
            self._redraw_locked()

    def finish(self, text: str | None = None) -> None:
        super().finish(text)

    def _line(self) -> str:
        elapsed = int(time.monotonic() - self._started)
        if self._current is not None:
            bar = format_extract_line(
                self._current,
                self._total,
                width=self.width,
                listing=self.listing,
                **self._bar_style(),
            )
            return f"{bar}  ({elapsed}s)"
        return f"{self._label}  ({elapsed}s)"

    def _redraw_locked(self) -> None:
        self._draw(self._line())

    def _heartbeat_line(self) -> str:
        return self._line()


class YtdlpLogger:
    """Translate yt-dlp to_screen messages into extract progress and surface warnings."""

    def __init__(
        self,
        progress: ExtractProgress | None = None,
        *,
        site: str | None = None,
        emit_warnings: bool = True,
        emit_errors: bool = True,
    ) -> None:
        self.progress = progress
        self.site = site or (progress.site if progress is not None else "YouTube")
        self.emit_warnings = emit_warnings
        self.emit_errors = emit_errors
        self._have_items = False
        self.warnings: list[str] = []
        self.errors: list[str] = []

    def debug(self, message: str) -> None:
        if self.progress is None or not self.progress.enabled:
            return
        text = strip_ansi(str(message))
        if text.startswith("[debug]"):
            return
        parsed = parse_playlist_item(text)
        if parsed:
            self._have_items = True
            self.progress.item(*parsed)
            return
        if self._have_items:
            return
        lowered = text.lower()
        listing = self.progress.listing
        if "extracting url" in lowered:
            self.progress.status(f"Connecting to {self.site}…")
        elif "webpage" in lowered:
            self.progress.status(f"Loading {listing} page…")
        elif "player" in lowered:
            self.progress.status("Loading player…")
        elif "api" in lowered:
            self.progress.status(f"Fetching {listing} data…")
        elif "downloading" in lowered:
            self.progress.status(f"Talking to {self.site}…")

    def warning(self, message: str) -> None:
        from yt_dlp_emby.log import warn

        text = strip_ansi(str(message)).strip()
        if not text:
            return
        self.warnings.append(text)
        if self.emit_warnings:
            warn(text)

    def error(self, message: str) -> None:
        from yt_dlp_emby.log import error

        text = strip_ansi(str(message)).strip()
        if not text:
            return
        self.errors.append(text)
        if self.emit_errors:
            error(text)


def copy_with_progress(
    src: Path,
    dest: Path,
    progress: DownloadProgress | None = None,
    *,
    label: str = "copy",
    min_size: int = _COPY_BAR_MIN,
) -> None:
    size = src.stat().st_size
    if progress is None or not progress.enabled or size < min_size:
        shutil.copyfile(src, dest)
        return
    copied = 0
    with src.open("rb") as inf, dest.open("wb") as outf:
        while True:
            chunk = inf.read(1024 * 1024)
            if not chunk:
                break
            outf.write(chunk)
            copied += len(chunk)
            progress.copy_update(copied, size, label=label)
