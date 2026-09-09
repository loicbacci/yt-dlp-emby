"""Download a single video with yt-dlp into an Emby episode path."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL

from yt_emby.auth import YoutubeAuthError, auth_error_from_exception
from yt_emby.config import Settings
from yt_emby.extract import js_runtime_opts
from yt_emby.progress import DownloadProgress, copy_with_progress

DEFAULT_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/bv+ba/b"
LOW_RES_FORMAT = "worst[height<=144]/worst"
TARGET_HEIGHT = 1080
_SKIP_SUFFIXES = (".part", ".ytdl", ".temp")


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
    """Copy finished episode files from local staging onto the library path."""
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    stem = src_stem.name
    if not src_stem.parent.is_dir():
        return
    for path in src_stem.parent.iterdir():
        if not path.is_file() or not path.name.startswith(stem):
            continue
        rest = path.name[len(stem) :]
        if not (rest.startswith(".") or rest.startswith("-")):
            continue
        if rest.endswith(_SKIP_SUFFIXES):
            continue
        label = "copy" if rest == ".mkv" else rest.lstrip(".-") or "copy"
        copy_to_library(
            path,
            dest_stem.parent / f"{dest_stem.name}{rest}",
            progress,
            label=label,
        )
    if progress is not None:
        progress.close()


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
    if settings.cookiefile:
        opts["cookiefile"] = str(settings.cookiefile)
    opts.update(js_runtime_opts())
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
    if not info:
        raise RuntimeError(
            "no downloadable media (upcoming live/premiere, unavailable, or extractor error)"
        )
    return info
