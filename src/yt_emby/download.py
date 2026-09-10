"""Download a single video with yt-dlp into an Emby episode path."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL

from yt_emby.auth import YoutubeAuthError, auth_error_from_exception
from yt_emby.config import Settings
from yt_emby.cookies import sandbox_cookiefile
from yt_emby.extract import js_runtime_opts
from yt_emby.progress import DownloadProgress, copy_with_progress

DEFAULT_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/bv+ba/b"
LOW_RES_FORMAT = "worst[height<=144]/worst"
TARGET_HEIGHT = 1080
_VIDEO_EXTS = {".mkv", ".mp4", ".webm", ".m4a", ".m4v"}
_STALE_STAGING_PREFIX = "yt-emby-"
_STAGING_PID = ".yt-emby-pid"


def mark_live_staging(work_dir: Path) -> None:
    """Record this process so a later launch will not delete this run's temp dir."""
    (work_dir / _STAGING_PID).write_text(str(os.getpid()), encoding="utf-8")


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True


def _staging_in_use(path: Path) -> bool:
    if not path.is_dir():
        return False
    try:
        text = (path / _STAGING_PID).read_text(encoding="utf-8").strip()
        pid = int(text)
    except (OSError, ValueError):
        return False
    return _pid_is_running(pid)


class _YdlErrorLog:
    """Keep yt-dlp ERROR lines so ignoreerrors does not hide login failures."""

    def __init__(self, *, verbose: bool) -> None:
        self.errors: list[str] = []
        self.verbose = verbose

    def debug(self, message: str) -> None:
        if self.verbose:
            sys.stderr.write(f"{message}\n")

    def info(self, message: str) -> None:
        self.debug(message)

    def warning(self, message: str) -> None:
        if self.verbose:
            sys.stderr.write(f"{message}\n")

    def error(self, message: str) -> None:
        text = str(message)
        self.errors.append(text)
        sys.stderr.write(f"ERROR: {text}\n")


def cleanup_stale_staging(
    staging: Path | None = None,
    *,
    temp_dir: Path | None = None,
) -> int:
    """Remove leftover run dirs and cookie copies that cannot be resumed.

    Each download uses a unique `yt-emby-*` directory, so leftovers from a
    killed process cannot be continued and only take disk. Directories still
    owned by a running yt-emby process are left alone.
    """
    removed = 0
    roots: list[Path] = [Path(temp_dir) if temp_dir is not None else Path(tempfile.gettempdir())]
    if staging is not None:
        roots.append(Path(staging))
    seen: set[Path] = set()
    for root in roots:
        try:
            resolved = root.resolve()
        except OSError:
            continue
        if resolved in seen or not root.is_dir():
            continue
        seen.add(resolved)
        try:
            children = list(root.iterdir())
        except OSError:
            continue
        for path in children:
            if not path.name.startswith(_STALE_STAGING_PREFIX):
                continue
            if _staging_in_use(path):
                continue
            try:
                if path.is_dir():
                    shutil.rmtree(path)
                elif path.is_file():
                    path.unlink()
                else:
                    continue
            except OSError:
                continue
            removed += 1
    return removed


def _stem_files(src_stem: Path) -> list[Path]:
    stem = src_stem.name
    parent = src_stem.parent
    if not parent.is_dir():
        return []
    found: list[Path] = []
    for path in parent.iterdir():
        if not path.is_file() or not path.name.startswith(stem):
            continue
        rest = path.name[len(stem) :]
        if rest.startswith(".") or rest.startswith("-"):
            found.append(path)
    return found


def remove_staged_episode(src_stem: Path) -> None:
    for path in _stem_files(src_stem):
        try:
            path.unlink()
        except OSError:
            pass


def _is_library_artifact(rest: str) -> bool:
    """True for the finished .mkv and subtitle sidecars, not yt-dlp temps or stream fragments."""
    lower = rest.lower()
    if lower == ".mkv":
        return True
    if not lower.startswith(".") or not lower.endswith(".srt"):
        return False
    return not any(ext in lower for ext in _VIDEO_EXTS)


def video_height(path: Path, ffmpeg: Path) -> int | None:
    """Return the video stream height, or None if it cannot be probed."""
    probe = ffmpeg.with_name("ffprobe")
    if not probe.is_file():
        found = shutil.which("ffprobe")
        probe = Path(found) if found else probe
    if not probe.is_file():
        return None
    try:
        result = subprocess.run(
            [
                str(probe),
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=height",
                "-of",
                "csv=p=0",
                str(path),
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except OSError:
        return None
    text = (result.stdout or "").strip().splitlines()
    if not text:
        return None
    try:
        return int(text[0])
    except ValueError:
        return None


def copy_to_library(
    src: Path,
    dest: Path,
    progress: DownloadProgress | None = None,
    *,
    label: str = "copy",
) -> None:
    """Copy file bytes. Ignore CIFS failures when preserving timestamps/mode."""
    copy_with_progress(src, dest, progress, label=label)
    try:
        shutil.copystat(src, dest)
    except OSError:
        return


def promote_episode(
    src_stem: Path,
    dest_stem: Path,
    progress: DownloadProgress | None = None,
) -> None:
    """Copy finished episode files from local staging onto the library path, then delete them."""
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    stem = src_stem.name
    staged = _stem_files(src_stem)
    copied = False
    for path in staged:
        rest = path.name[len(stem) :]
        if not _is_library_artifact(rest):
            continue
        if path.stat().st_size == 0:
            continue
        label = "copy" if rest == ".mkv" else rest.lstrip(".-") or "copy"
        copy_to_library(
            path,
            dest_stem.parent / f"{dest_stem.name}{rest}",
            progress,
            label=label,
        )
        copied = True
    if progress is not None:
        progress.close()
    if copied:
        remove_staged_episode(src_stem)


def download_video(
    url: str,
    dest_stem: Path,
    settings: Settings,
    *,
    format_selector: str | None = None,
    subtitleslangs: list[str] | None = None,
) -> dict[str, Any]:
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    progress = DownloadProgress(enabled=settings.show_progress)
    opts: dict[str, Any] = {
        "format": format_selector or DEFAULT_FORMAT,
        "merge_output_format": "mkv",
        "final_ext": "mkv",
        "keepvideo": False,
        "outtmpl": str(dest_stem) + ".%(ext)s",
        "writesubtitles": True,
        "writeautomaticsub": False,
        "subtitleslangs": subtitleslangs if subtitleslangs is not None else ["en"],
        "ffmpeg_location": str(settings.ffmpeg),
        "noprogress": not settings.verbose,
        "quiet": not settings.verbose,
        "verbose": settings.verbose,
        "no_warnings": not settings.verbose,
        "overwrites": True,
        "ignoreerrors": True,
        "sleep_interval": 1,
        "sleep_interval_subtitles": 1,
        "progress_hooks": [progress.hook] if settings.show_progress else [],
        "postprocessor_hooks": [progress.postprocessor_hook] if settings.show_progress else [],
        "postprocessors": [
            {"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"},
            {"key": "FFmpegSubtitlesConvertor", "format": "srt"},
        ],
    }
    if settings.cookies_from_browser:
        opts["cookiesfrombrowser"] = (settings.cookies_from_browser,)
    log = _YdlErrorLog(verbose=settings.verbose)
    opts["logger"] = log
    opts.update(js_runtime_opts())
    with sandbox_cookiefile(
        str(settings.cookiefile) if settings.cookiefile else None
    ) as cookiefile:
        if cookiefile:
            opts["cookiefile"] = cookiefile
        try:
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(url, download=True)
        except Exception as exc:
            progress.close()
            auth = auth_error_from_exception(url, exc)
            if auth is not None:
                raise auth from exc
            raise
    progress.close()
    mkv = dest_stem.with_suffix(".mkv")
    ok = bool(info and info.get("id") and mkv.is_file() and mkv.stat().st_size > 0)
    if ok:
        return info
    blob = "\n".join(log.errors)
    auth = auth_error_from_exception(url, RuntimeError(blob or "download failed"))
    if auth is not None:
        raise auth
    if blob.strip():
        raise RuntimeError(blob.strip())
    raise RuntimeError("download did not produce an mkv (merge or remux failed)")
