"""Small launcher for the web application; media operations use private workers."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from yt_dlp_emby.config import env_value


def _port(value: str) -> int:
    try:
        port = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("port must be an integer") from exc
    if not 1 <= port <= 65535:
        raise argparse.ArgumentTypeError("port must be between 1 and 65535")
    return port


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="yt-dlp-emby",
        description="Serve the yt-dlp-emby web application. Manage media in the web UI.",
    )
    parser.add_argument("--host", default="127.0.0.1", help="Bind address (default: localhost)")
    parser.add_argument("--port", type=_port, default=os.environ.get("PORT", "8080"))
    parser.add_argument("--data", dest="data_dir", type=Path, help="Application data directory")
    parser.add_argument(
        "--proxy-headers", action="store_true", help="Trust configured proxy headers"
    )
    return parser


def run_server(args: argparse.Namespace) -> int:
    from yt_dlp_emby.server.app import serve

    flag = str(env_value(os.environ, "PROXY_HEADERS") or "").strip().lower()
    serve(
        host=args.host,
        port=args.port,
        data_dir=args.data_dir,
        proxy_headers=args.proxy_headers or flag in {"1", "true", "yes", "on"},
    )
    return 0


def main(argv: list[str] | None = None) -> None:
    raise SystemExit(run_server(build_parser().parse_args(argv)))
