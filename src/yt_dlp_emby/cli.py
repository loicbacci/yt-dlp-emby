"""Command-line interface."""

from __future__ import annotations

import argparse
import sys

from pathlib import Path

from yt_dlp_emby.config import ConfigError, Settings, resolve_settings
from yt_dlp_emby.ffmpeg import FFmpegNotFoundError


def _add_verbosity(parser: argparse.ArgumentParser) -> None:
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--quiet",
        action="store_true",
        help="Hide progress bars and step logs; still print warnings and the run summary",
    )
    verbosity.add_argument(
        "--silent",
        action="store_true",
        help="Hide everything except errors",
    )
    verbosity.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Print all yt-dlp messages (extractor, HTTP, warnings)",
    )


def _add_debug(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-vv",
        "--debug",
        action="store_true",
        dest="debug",
        help="Show listing vs disk timings (does not dump yt-dlp HTTP or hide progress)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-dlp-emby",
        description="Download YouTube or Dropout.tv videos with yt-dlp for Emby.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor = sub.add_parser("doctor", help="Check ffmpeg, Node, cookies, staging, and disk space")
    doctor.add_argument("--ffmpeg-location", help="Path to ffmpeg or its directory")
    doctor.add_argument("--cookies", help="Netscape cookies.txt to verify")
    doctor.add_argument("--staging", help="Local staging directory to verify (writable + free space)")
    doctor.add_argument("--library", help="Library directory to verify (exists + free space)")

    youtube = sub.add_parser("youtube", help="Download YouTube playlists into an Emby library")
    youtube.add_argument(
        "url",
        nargs="?",
        help="Playlist or video URL (omit to use youtube.yaml)",
    )
    youtube.add_argument(
        "--manifest",
        help="Path to youtube.yaml (default: youtube.yaml in the current directory if that file exists)",
    )
    youtube.add_argument("--library", help="Emby library root directory")
    youtube.add_argument("--old-dir", help="Directory for replaced or removed files")
    youtube.add_argument("--config", help="Path to a TOML config file")
    youtube.add_argument("--season", type=int, help="Force season number (URL mode only)")
    youtube.add_argument(
        "--series",
        action="append",
        dest="series_filter",
        metavar="NAME",
        help="Only this series name or playlist URL substring (manifest mode, repeatable)",
    )
    youtube.add_argument("--dry-run", action="store_true", help="Print planned actions without writing")
    _add_verbosity(youtube)
    _add_debug(youtube)
    youtube.add_argument("--cookies-from-browser", help="Browser name for yt-dlp cookies")
    youtube.add_argument(
        "--cookies",
        help="Netscape cookies.txt for YouTube (default: cookies.txt in the current directory if that file exists)",
    )
    youtube.add_argument("--ffmpeg-location", help="Path to ffmpeg or its directory")
    youtube.add_argument(
        "--staging",
        help="Local directory for in-progress downloads (recommended on SMB/NFS). Defaults to the system temp dir.",
    )
    youtube.add_argument("--format", help="yt-dlp format selector override")
    youtube.add_argument(
        "--force-refetch",
        action="store_true",
        help="Ignore cached video metadata and fetch it again (playlist listing still runs first)",
    )

    dropout = sub.add_parser("dropout", help="Download Dropout.tv seasons into an existing Emby/TVDB library")
    dropout.add_argument(
        "--manifest",
        help="Path to dropout.yaml (default: dropout.yaml in the current directory if that file exists)",
    )
    dropout.add_argument("--library", help="Emby library root directory (overrides manifest)")
    dropout.add_argument("--old-dir", help="Directory for replaced files (overrides manifest)")
    dropout.add_argument("--dry-run", action="store_true", help="Print planned actions without writing")
    dropout.add_argument(
        "--force",
        action="store_true",
        help="Redownload even when the destination .mkv already exists",
    )
    dropout.add_argument(
        "--series",
        action="append",
        dest="series_filter",
        metavar="NAME",
        help="Only this series name or folder (repeatable)",
    )
    dropout.add_argument(
        "--season",
        type=int,
        action="append",
        dest="season_filter",
        metavar="N",
        help="Only this Dropout season number (repeatable)",
    )
    dropout.add_argument(
        "--create",
        action="store_true",
        help="Create missing Emby series folders instead of refusing",
    )
    _add_verbosity(dropout)
    dropout.add_argument("--cookies-from-browser", help="Browser name for yt-dlp cookies")
    dropout.add_argument("--cookies", help="Netscape cookies.txt for Dropout (overrides manifest)")
    dropout.add_argument("--ffmpeg-location", help="Path to ffmpeg or its directory")
    dropout.add_argument(
        "--staging",
        help="Local directory for in-progress downloads. Defaults to the system temp dir.",
    )
    dropout.add_argument("--format", help="yt-dlp format selector override")
    dropout.add_argument(
        "--force-refetch",
        action="store_true",
        help="Ignore cached Dropout season listings and fetch them again",
    )
    _add_debug(dropout)

    bench = sub.add_parser("bench", help="Measure copy speed from local disk onto the library share")
    bench.add_argument(
        "--dest",
        help="Directory to copy into (default: bench_dest from config, else library)",
    )
    bench.add_argument(
        "--size",
        default="256M",
        help="Payload size, e.g. 64M, 256M, 1G (default: 256M)",
    )
    bench.add_argument("--library", help="Emby library root (used when --dest / bench_dest are unset)")
    bench.add_argument("--old-dir", help="Directory for replaced files (needed to resolve config)")
    bench.add_argument("--config", help="Path to a TOML config file")
    bench.add_argument(
        "--staging",
        help="Local directory for the source file. Defaults to the system temp dir.",
    )
    _add_verbosity(bench)
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
        silent=bool(getattr(args, "silent", False)),
        verbose=bool(getattr(args, "verbose", False)),
        debug=bool(getattr(args, "debug", False)),
        staging=getattr(args, "staging", None),
        force_refetch=bool(getattr(args, "force_refetch", False)),
        bench_dest=getattr(args, "dest", None),
    )


def run_doctor(args: argparse.Namespace) -> int:
    from yt_dlp_emby.doctor import run_doctor as doctor_run

    return doctor_run(
        ffmpeg_location=getattr(args, "ffmpeg_location", None),
        cookies=getattr(args, "cookies", None),
        staging=getattr(args, "staging", None),
        library=getattr(args, "library", None),
    )


def run_bench(args: argparse.Namespace) -> int:
    from yt_dlp_emby.bench import parse_size, run_bench as bench_run

    try:
        settings = _settings_from_args(args)
        size = parse_size(str(args.size))
    except (ConfigError, FFmpegNotFoundError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    dest = settings.bench_dest or settings.library
    return bench_run(
        dest,
        size=size,
        source_dir=settings.staging,
        show_progress=settings.show_progress,
    )


def _youtube_manifest_path(args: argparse.Namespace) -> Path:
    if args.manifest:
        return Path(args.manifest)
    default = Path.cwd() / "youtube.yaml"
    if default.is_file():
        return default
    raise ConfigError(
        "Missing YouTube URL or manifest. Pass a playlist URL, --manifest, or put youtube.yaml in the current directory."
    )


def run_download(args: argparse.Namespace) -> int:
    from yt_dlp_emby.pipeline import run_download as pipeline_download
    from yt_dlp_emby.pipeline import run_youtube_manifest
    from yt_dlp_emby.youtube_manifest import filter_youtube_manifest, load_youtube_manifest

    if args.url:
        if getattr(args, "series_filter", None):
            print("error: --series is only used with a youtube.yaml manifest", file=sys.stderr)
            return 1
        try:
            settings = _settings_from_args(args)
        except (ConfigError, FFmpegNotFoundError) as exc:
            print(exc, file=sys.stderr)
            return 1
        return pipeline_download(args.url, settings, format_selector=getattr(args, "format", None))

    if getattr(args, "season", None) is not None:
        print("error: --season is for a single URL; set season: on the playlist in youtube.yaml", file=sys.stderr)
        return 1

    try:
        manifest = load_youtube_manifest(_youtube_manifest_path(args))
        manifest = filter_youtube_manifest(
            manifest,
            series_names=getattr(args, "series_filter", None),
        )
        settings = resolve_settings(
            library=getattr(args, "library", None) or str(manifest.library),
            old_dir=getattr(args, "old_dir", None) or str(manifest.old_dir),
            ffmpeg_location=getattr(args, "ffmpeg_location", None),
            cookies_from_browser=getattr(args, "cookies_from_browser", None),
            cookiefile=getattr(args, "cookies", None)
            or (str(manifest.cookies) if manifest.cookies else None),
            dry_run=bool(getattr(args, "dry_run", False)),
            quiet=bool(getattr(args, "quiet", False)),
            silent=bool(getattr(args, "silent", False)),
            verbose=bool(getattr(args, "verbose", False)),
            debug=bool(getattr(args, "debug", False)),
            staging=getattr(args, "staging", None)
            or (str(manifest.staging) if manifest.staging else None),
            force_refetch=bool(getattr(args, "force_refetch", False)),
            use_default_config=False,
            auto_cookies=False,
        )
        return run_youtube_manifest(
            manifest,
            settings,
            format_selector=getattr(args, "format", None),
        )
    except (ConfigError, FFmpegNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 1


def _dropout_manifest_path(args: argparse.Namespace) -> Path:
    if args.manifest:
        return Path(args.manifest)
    default = Path.cwd() / "dropout.yaml"
    if default.is_file():
        return default
    raise ConfigError(
        "Missing Dropout manifest. Pass --manifest or put dropout.yaml in the current directory."
    )


def run_dropout(args: argparse.Namespace) -> int:
    from yt_dlp_emby.dropout import run_dropout as pipeline_dropout
    from yt_dlp_emby.dropout_manifest import load_dropout_manifest

    try:
        manifest = load_dropout_manifest(_dropout_manifest_path(args))
        from yt_dlp_emby.dropout_manifest import filter_dropout_manifest

        manifest = filter_dropout_manifest(
            manifest,
            series_names=getattr(args, "series_filter", None),
            dropout_seasons=getattr(args, "season_filter", None),
        )
        settings = resolve_settings(
            library=getattr(args, "library", None) or str(manifest.library),
            old_dir=getattr(args, "old_dir", None) or str(manifest.old_dir),
            ffmpeg_location=getattr(args, "ffmpeg_location", None),
            cookies_from_browser=getattr(args, "cookies_from_browser", None),
            cookiefile=getattr(args, "cookies", None)
            or (str(manifest.cookies) if manifest.cookies else None),
            dry_run=bool(getattr(args, "dry_run", False)),
            quiet=bool(getattr(args, "quiet", False)),
            silent=bool(getattr(args, "silent", False)),
            verbose=bool(getattr(args, "verbose", False)),
            debug=bool(getattr(args, "debug", False)),
            staging=getattr(args, "staging", None)
            or (str(manifest.staging) if manifest.staging else None),
            force_refetch=bool(getattr(args, "force_refetch", False)),
            use_default_config=False,
            auto_cookies=False,
        )
        return pipeline_dropout(
            manifest,
            settings,
            force=bool(getattr(args, "force", False)),
            create=bool(getattr(args, "create", False)),
            format_selector=getattr(args, "format", None),
        )
    except (ConfigError, FFmpegNotFoundError) as exc:
        print(exc, file=sys.stderr)
        return 1


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "doctor":
            code = run_doctor(args)
        elif args.command == "bench":
            code = run_bench(args)
        elif args.command == "youtube":
            code = run_download(args)
        elif args.command == "dropout":
            code = run_dropout(args)
        else:
            parser.error(f"unknown command {args.command}")
            return
    except KeyboardInterrupt:
        print("error: interrupted", file=sys.stderr, flush=True)
        raise SystemExit(130) from None
    raise SystemExit(code)


if __name__ == "__main__":
    main()
