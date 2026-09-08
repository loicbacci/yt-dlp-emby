"""Download a single video with yt-dlp into an Emby episode path."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from yt_dlp import YoutubeDL

from yt_emby.config import Settings

DEFAULT_FORMAT = "bv*[height<=1080]+ba/b[height<=1080]/bv+ba/b"
LOW_RES_FORMAT = "worst[height<=144]/worst"


def download_video(
    url: str,
    dest_stem: Path,
    settings: Settings,
    *,
    format_selector: str | None = None,
) -> None:
    dest_stem.parent.mkdir(parents=True, exist_ok=True)
    opts: dict[str, Any] = {
        "format": format_selector or DEFAULT_FORMAT,
        "merge_output_format": "mkv",
        "outtmpl": str(dest_stem) + ".%(ext)s",
        "writesubtitles": True,
        "writeautomaticsub": True,
        "subtitleslangs": ["en", "en-orig"],
        "ffmpeg_location": str(settings.ffmpeg),
        "noprogress": True,
        "quiet": True,
        "no_warnings": True,
        "overwrites": True,
        "extractor_args": {"youtube": {"player_client": ["tv", "android", "web"]}},
        "postprocessors": [
            {"key": "FFmpegVideoRemuxer", "preferedformat": "mkv"},
            {"key": "FFmpegSubtitlesConvertor", "format": "srt"},
        ],
    }
    if settings.cookies_from_browser:
        opts["cookiesfrombrowser"] = (settings.cookies_from_browser,)
    with YoutubeDL(opts) as ydl:
        ydl.download([url])
