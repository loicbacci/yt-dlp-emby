"""Measure local-to-library copy speed (the promote step onto SMB/NFS)."""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from pathlib import Path

from yt_dlp_emby.download import copy_to_library
from yt_dlp_emby.log import error, info
from yt_dlp_emby.progress import DownloadProgress, format_bytes
from yt_dlp_emby.style import dim, green

BENCH_NAME = ".yt-dlp-emby-bench.bin"
DEFAULT_SIZE = 256 * 1024 * 1024
_UNITS = {
    "B": 1,
    "K": 1024,
    "KB": 1024,
    "KIB": 1024,
    "M": 1024**2,
    "MB": 1024**2,
    "MIB": 1024**2,
    "G": 1024**3,
    "GB": 1024**3,
    "GIB": 1024**3,
}


def parse_size(text: str) -> int:
    raw = text.strip().replace(" ", "").upper()
    if not raw:
        raise ValueError("size is empty")
    suffix = ""
    number = raw
    for candidate in sorted(_UNITS, key=len, reverse=True):
        if raw.endswith(candidate):
            suffix = candidate
            number = raw[: -len(candidate)]
            break
    if not number:
        raise ValueError(f"invalid size: {text}")
    try:
        value = float(number) if "." in number else int(number)
    except ValueError as exc:
        raise ValueError(f"invalid size: {text}") from exc
    size = int(value * _UNITS.get(suffix, 1))
    if size < 1:
        raise ValueError("size must be at least 1 byte")
    return size


def format_rate(nbytes: int, seconds: float) -> str:
    if seconds <= 0:
        return "?/s"
    return f"{format_bytes(nbytes / seconds)}/s"


def default_link_mbit() -> tuple[str, int] | None:
    try:
        with open("/proc/net/route", encoding="utf-8") as handle:
            next(handle)
            for line in handle:
                parts = line.split()
                if len(parts) >= 2 and parts[1] == "00000000":
                    name = parts[0]
                    speed = Path(f"/sys/class/net/{name}/speed")
                    mbit = int(speed.read_text(encoding="utf-8").strip())
                    if mbit > 0:
                        return name, mbit
    except (OSError, ValueError):
        return None
    return None


def _write_payload(path: Path, size: int) -> None:
    chunk = os.urandom(min(size, 1024 * 1024))
    remaining = size
    with path.open("wb") as handle:
        while remaining:
            piece = chunk if remaining >= len(chunk) else chunk[:remaining]
            handle.write(piece)
            remaining -= len(piece)


def _time_copy(label: str, fn) -> tuple[str, float]:
    started = time.perf_counter()
    fn()
    elapsed = time.perf_counter() - started
    return label, elapsed


def run_bench(
    dest_dir: Path,
    *,
    size: int = DEFAULT_SIZE,
    source_dir: Path | None = None,
    show_progress: bool = True,
) -> int:
    dest_dir = Path(dest_dir)
    try:
        dest_dir.mkdir(parents=True, exist_ok=True)
        probe = dest_dir / f"{BENCH_NAME}.probe"
        probe.write_bytes(b"ok")
        probe.unlink()
    except OSError as exc:
        error(f"cannot write to {dest_dir}: {exc}")
        return 1

    link = default_link_mbit()
    if link:
        name, mbit = link
        theoretical = (mbit * 1_000_000) / 8 / (1024 * 1024)
        info(
            dim(
                f"default route {name}  {mbit} Mb/s  "
                f"(~{theoretical:.0f} MiB/s if the link is the limit)"
            )
        )
    info(f"payload  {format_bytes(float(size))}  local → {dest_dir}")

    staging = Path(source_dir) if source_dir is not None else Path(tempfile.gettempdir())
    staging.mkdir(parents=True, exist_ok=True)
    app_dest = dest_dir / BENCH_NAME
    baseline_dest = dest_dir / f"{BENCH_NAME}.copyfile"
    src: Path | None = None
    try:
        fd, tmp = tempfile.mkstemp(prefix="yt-dlp-emby-bench-", suffix=".bin", dir=str(staging))
        os.close(fd)
        src = Path(tmp)
        _write_payload(src, size)
        progress = DownloadProgress(enabled=show_progress)

        def app_copy() -> None:
            copy_to_library(src, app_dest, progress, label="copy")

        _, app_seconds = _time_copy("app", app_copy)
        progress.close()
        info(
            f"{green('app copy')}     {format_rate(size, app_seconds)}  "
            f"{app_seconds:.1f}s  (same path as promoting an episode)"
        )

        def baseline() -> None:
            shutil.copyfile(src, baseline_dest)

        _, base_seconds = _time_copy("copyfile", baseline)
        info(
            f"{green('copyfile')}     {format_rate(size, base_seconds)}  "
            f"{base_seconds:.1f}s  (shutil.copyfile, no progress bar)"
        )
        if app_seconds > 0 and base_seconds > 0:
            ratio = app_seconds / base_seconds
            if ratio >= 1.15:
                info(dim(f"app copy is {ratio:.1f}x slower than copyfile"))
            else:
                info(dim("app copy is in line with copyfile; the share/link is the limit"))
    except OSError as exc:
        error(str(exc))
        return 1
    finally:
        for path in (app_dest, baseline_dest, src):
            if path is None:
                continue
            try:
                path.unlink(missing_ok=True)
            except OSError:
                pass
    return 0
