"""Health checks for ffmpeg, Node, cookies, staging, and disk space."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Mapping

from yt_dlp_emby.config import env_value
from yt_dlp_emby.cookies import cookies_file_usable
from yt_dlp_emby.extract import find_node
from yt_dlp_emby.ffmpeg import FFmpegNotFoundError, find_ffmpeg
from yt_dlp_emby.log import info, warn
from yt_dlp_emby.style import dim, green

WARN_FREE_BYTES = 2 * 1024 * 1024 * 1024
FAIL_FREE_BYTES = 200 * 1024 * 1024


def format_bytes(num: int) -> str:
    value = float(num)
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(value) < 1024.0 or unit == "TiB":
            return f"{value:.1f}{unit}"
        value /= 1024.0
    return f"{value:.1f}TiB"


def _report_disk(path: Path, label: str) -> int:
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        warn(f"could not read free space for {label} ({path}): {exc}")
        return 0
    info(f"{green('ok')}      {label:7} {format_bytes(usage.free)} free")
    if usage.free < FAIL_FREE_BYTES:
        warn(
            f"{label} has only {format_bytes(usage.free)} free "
            f"(need about {format_bytes(FAIL_FREE_BYTES)})"
        )
        return 1
    if usage.free < WARN_FREE_BYTES:
        warn(f"{label} has {format_bytes(usage.free)} free; large downloads may fill the disk")
    return 0


def run_doctor(
    *,
    ffmpeg_location: str | None = None,
    cookies: str | None = None,
    staging: str | None = None,
    library: str | None = None,
    environ: Mapping[str, str] | None = None,
    cwd: Path | None = None,
) -> int:
    environ = os.environ if environ is None else environ
    cwd = Path.cwd() if cwd is None else cwd
    failed = 0

    try:
        ffmpeg = find_ffmpeg(ffmpeg_location, environ=environ)
        info(f"{green('ok')}      ffmpeg  {ffmpeg}")
    except FFmpegNotFoundError as exc:
        warn(str(exc).splitlines()[0])
        failed += 1

    node = find_node()
    if node:
        info(f"{green('ok')}      node    {node}")
    else:
        warn("node not found on PATH (needed for YouTube JS challenges / 1080p)")

    cookie_path: Path | None = None
    if cookies:
        cookie_path = Path(cookies)
        if not cookie_path.is_absolute():
            cookie_path = cwd / cookie_path
    else:
        default = cwd / "cookies.txt"
        if default.is_file():
            cookie_path = default
    if cookie_path is None:
        info(f"{dim('skip')}    cookies  (pass --cookies or put cookies.txt in the current directory)")
    elif not cookie_path.is_file():
        warn(f"cookies file not found: {cookie_path}")
        failed += 1
    elif not cookies_file_usable(cookie_path):
        warn(f"cookies file is empty: {cookie_path}")
        failed += 1
    else:
        info(f"{green('ok')}      cookies {cookie_path}")

    if staging:
        staging_path = Path(staging)
        try:
            staging_path.mkdir(parents=True, exist_ok=True)
            probe = staging_path / ".yt-dlp-emby-doctor"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink()
            info(f"{green('ok')}      staging {staging_path}")
            failed += _report_disk(staging_path, "staging")
        except OSError as exc:
            warn(f"staging is not writable: {staging_path} ({exc})")
            failed += 1
    else:
        env_staging = env_value(environ, "STAGING")
        if env_staging:
            staging_path = Path(env_staging)
            if staging_path.exists():
                info(f"{green('ok')}      staging {staging_path}")
                failed += _report_disk(staging_path, "staging")

    library_path: Path | None = None
    env_library = env_value(environ, "LIBRARY")
    if library:
        library_path = Path(library)
    elif env_library:
        library_path = Path(env_library)
    if library_path is not None:
        if not library_path.exists():
            warn(f"library does not exist: {library_path}")
            failed += 1
        else:
            info(f"{green('ok')}      library {library_path}")
            failed += _report_disk(library_path, "library")

    if not staging:
        tmp = Path(environ.get("TMPDIR") or environ.get("TMP") or "/tmp")
        if tmp.exists():
            _report_disk(tmp, "temp")

    if failed:
        warn(f"doctor found {failed} problem(s)")
        return 1
    info(green("doctor: all required checks passed"))
    return 0
