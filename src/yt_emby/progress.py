"""A compact progress bar driven by yt-dlp hooks and log messages."""

from __future__ import annotations

import re
import sys
import threading
import time
from typing import Any, TextIO

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_ITEM = re.compile(r"Downloading item (\d+) of (\d+)")
_ITEM_UNKNOWN = re.compile(r"Downloading item (\d+) of ")


def strip_ansi(text: str) -> str:
    return _ANSI.sub("", text)


def parse_playlist_item(message: str) -> tuple[int, int | None] | None:
    clean = strip_ansi(message)
    match = _ITEM.search(clean)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = _ITEM_UNKNOWN.search(clean)
    if match:
        return int(match.group(1)), None
    return None


def format_bytes(num: float | None) -> str:
    if num is None:
        return "?"
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB"):
        if abs(value) < 1024.0 or unit == "GiB":
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}GiB"


def format_eta(seconds: float | None) -> str:
    if seconds is None:
        return "--:--"
    total = max(0, int(seconds))
    minutes, secs = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def render_bar(percent: float, width: int = 28) -> str:
    width = max(1, width)
    filled = int(round((percent / 100.0) * width))
    filled = min(width, max(0, filled))
    return "#" * filled + "-" * (width - filled)


def format_progress_line(data: dict[str, Any], width: int = 28) -> str:
    downloaded = data.get("downloaded_bytes") or 0
    total = data.get("total_bytes") or data.get("total_bytes_estimate")
    speed = data.get("speed")
    eta = data.get("eta")
    if total:
        percent = min(100.0, (downloaded / total) * 100.0)
        bar = render_bar(percent, width=width)
        return (
            f"[{bar}] {percent:5.1f}%  "
            f"{format_bytes(downloaded)}/{format_bytes(total)}  "
            f"{format_bytes(speed)}/s  ETA {format_eta(eta)}"
        )
    return f"{format_bytes(downloaded)}  {format_bytes(speed)}/s"


def format_extract_line(current: int, total: int | None, width: int = 28) -> str:
    if total:
        percent = min(100.0, (current / total) * 100.0)
        bar = render_bar(percent, width=width)
        return f"[{bar}] {current}/{total}  Listing playlist"
    return f"{current} videos  Listing playlist"


class ProgressDisplay:
    """Render a single updating line on stderr."""

    def __init__(self, enabled: bool = True, stream: TextIO | None = None) -> None:
        self.enabled = enabled
        self.stream = stream if stream is not None else sys.stderr
        self._last_len = 0

    def _draw(self, text: str) -> None:
        if not self.enabled:
            return
        padded = text + " " * max(0, self._last_len - len(text))
        self.stream.write("\r" + padded)
        self.stream.flush()
        self._last_len = len(text)

    def finish(self, text: str | None = None) -> None:
        if not self.enabled:
            return
        if text:
            self._draw(text)
        self.stream.write("\n")
        self.stream.flush()
        self._last_len = 0


class DownloadProgress(ProgressDisplay):
    def hook(self, data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        status = data.get("status")
        if status == "downloading":
            self._draw(format_progress_line(data))
        elif status == "finished":
            self.finish("Download complete, remuxing…")

    def postprocessor_hook(self, data: dict[str, Any]) -> None:
        if not self.enabled:
            return
        name = str(data.get("postprocessor") or "")
        status = data.get("status")
        if "Remux" in name and status == "started":
            self._draw("Remuxing to mkv…")
        elif status == "finished" and "Remux" in name:
            self.finish("Remux complete")


class ExtractProgress(ProgressDisplay):
    """Status/item progress with an elapsed-time heartbeat so long YouTube waits look alive."""

    def __init__(
        self,
        enabled: bool = True,
        stream: TextIO | None = None,
        *,
        heartbeat: bool = False,
    ) -> None:
        super().__init__(enabled=enabled, stream=stream)
        self._label = "Working…"
        self._current: int | None = None
        self._total: int | None = None
        self._started = time.monotonic()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if enabled and heartbeat:
            self._thread = threading.Thread(target=self._run_heartbeat, name="yt-emby-progress", daemon=True)
            self._thread.start()

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
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.5)
        super().finish(text)

    def _run_heartbeat(self) -> None:
        while not self._stop.wait(1.0):
            with self._lock:
                self._redraw_locked()

    def _line(self) -> str:
        elapsed = int(time.monotonic() - self._started)
        if self._current is not None:
            return f"{format_extract_line(self._current, self._total)}  ({elapsed}s)"
        return f"{self._label}  ({elapsed}s)"

    def _redraw_locked(self) -> None:
        self._draw(self._line())


class YtdlpLogger:
    """Translate yt-dlp to_screen messages into extract progress (works even when quiet=True)."""

    def __init__(self, progress: ExtractProgress) -> None:
        self.progress = progress
        self._have_items = False

    def debug(self, message: str) -> None:
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
        if "extracting url" in lowered:
            self.progress.status("Connecting to YouTube…")
        elif "webpage" in lowered:
            self.progress.status("Loading playlist page…")
        elif "player" in lowered:
            self.progress.status("Loading YouTube player…")
        elif "api" in lowered:
            self.progress.status("Fetching playlist data…")
        elif "downloading" in lowered:
            self.progress.status("Talking to YouTube…")

    def warning(self, message: str) -> None:
        return

    def error(self, message: str) -> None:
        return
