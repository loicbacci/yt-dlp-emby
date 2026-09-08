"""Command-line interface."""

from __future__ import annotations

import argparse
import sys

from yt_emby.config import ConfigError, Settings, resolve_settings
from yt_emby.ffmpeg import FFmpegNotFoundError, find_ffmpeg


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-emby",
        description="Download YouTube playlists with yt-dlp and write Emby NFO metadata.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check that ffmpeg is available")
    doctor.add_argument("--ffmpeg-location", help="Path to ffmpeg or its directory")

    download = sub.add_parser("download", help="Download a playlist or video and write NFO files")
    download.add_argument("url", help="YouTube playlist or video URL")
    download.add_argument("--library", help="Emby library root directory")
    download.add_argument("--old-dir", help="Directory for replaced or removed files")
    download.add_argument("--config", help="Path to a TOML config file")
    download.add_argument("--season", type=int, help="Force season number for this playlist")
    download.add_argument("--dry-run", action="store_true", help="Print planned actions without writing")
    verbosity = download.add_mutually_exclusive_group()
    verbosity.add_argument("--quiet", action="store_true", help="Hide progress bars and extra logs")
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print all yt-dlp messages (extractor, HTTP, warnings)",
    )
    download.add_argument("--cookies-from-browser", help="Browser name for yt-dlp cookies")
    download.add_argument(
        "--cookies",
        help="Netscape cookies.txt for YouTube (default: cookies.txt in the current directory if that file exists)",
    )
    download.add_argument("--ffmpeg-location", help="Path to ffmpeg or its directory")
    download.add_argument(
        "--staging",
        help="Local directory for in-progress downloads (recommended on SMB/NFS). Defaults to the system temp dir.",
    )
    download.add_argument("--format", help="yt-dlp format selector override")
    download.add_argument(
        "--force-refetch",
        action="store_true",
        help="Ignore cached video metadata and fetch it again (playlist listing still runs first)",
    )
    return parser


def _settings_from_args(args: argparse.Namespace) -> Settings:
    return resolve_settings(
        library=getattr(args, "library", None),
        old_dir=getattr(args, "old_dir", None),
        config_path=getattr(args, "config", None),
        ffmpeg_location=getattr(args, "ffmpeg_location", None),
        season=getattr(args, "season", None),
        cookies_from_browser=getattr(args, "cookies_from_browser", None),
        cookiefile=getattr(args, "cookies", None),
        dry_run=bool(getattr(args, "dry_run", False)),
        quiet=bool(getattr(args, "quiet", False)),
        verbose=bool(getattr(args, "verbose", False)),
        staging=getattr(args, "staging", None),
        force_refetch=bool(getattr(args, "force_refetch", False)),
    )


def run_doctor(ffmpeg_location: str | None = None) -> int:
    try:
        path = find_ffmpeg(ffmpeg_location, environ=__import__("os").environ)
    except FFmpegNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"ffmpeg: {path}")
    return 0


def run_download(args: argparse.Namespace) -> int:
    try:
        settings = _settings_from_args(args)
    except (ConfigError, FFmpegNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 1

    from yt_emby.pipeline import run_download as pipeline_download

    return pipeline_download(args.url, settings, format_selector=getattr(args, "format", None))


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        code = run_doctor(args.ffmpeg_location)
    elif args.command == "download":
        code = run_download(args)
    else:
        parser.error(f"unknown command {args.command}")
        return
    raise SystemExit(code)


if __name__ == "__main__":
    main()
