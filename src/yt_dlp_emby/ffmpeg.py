"""Locate a system ffmpeg binary without bundling one."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Mapping

FFMPEG_INSTALL_HELP = """ffmpeg not found on PATH (needed to merge video+audio into mkv).

  Debian/Ubuntu:  sudo apt install ffmpeg
  Fedora:         sudo dnf install ffmpeg
  Arch:           sudo pacman -S ffmpeg
  macOS:          brew install ffmpeg
  Windows:        winget install Gyan.FFmpeg
"""


class FFmpegNotFoundError(Exception):
    """ffmpeg is not installed or the given path does not exist."""


def find_ffmpeg(explicit: str | None, environ: Mapping[str, str]) -> Path:
    candidate = explicit or environ.get("YT_DLP_EMBY_FFMPEG") or environ.get("YT_EMBY_FFMPEG")
    if candidate:
        path = Path(candidate).expanduser()
        if path.is_dir():
            path = path / "ffmpeg"
        if not path.is_file():
            raise FFmpegNotFoundError(
                f"ffmpeg-location {path} does not exist.\n{FFMPEG_INSTALL_HELP}"
            )
        return path.resolve()

    found = shutil.which("ffmpeg")
    if not found:
        raise FFmpegNotFoundError(FFMPEG_INSTALL_HELP)
    return Path(found).resolve()
