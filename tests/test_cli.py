import pytest

from yt_emby.cli import build_parser


def test_download_requires_url() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "download",
            "https://www.youtube.com/playlist?list=PLAYLIST_ID",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--dry-run",
        ]
    )
    assert args.command == "download"
    assert args.url.endswith("PLAYLIST_ID")
    assert args.dry_run is True
    assert args.library == "/lib"
    assert args.old_dir == "/old"


def test_doctor_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["doctor"])
    assert args.command == "doctor"


def test_download_accepts_season_and_cookies() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "download",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--season",
            "2",
            "--cookies-from-browser",
            "firefox",
        ]
    )
    assert args.season == 2
    assert args.cookies_from_browser == "firefox"


def test_download_accepts_verbose() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "download",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--verbose",
        ]
    )
    assert args.verbose is True
    assert args.quiet is False


def test_quiet_and_verbose_are_exclusive() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "download",
                "https://example.invalid/watch?v=abc",
                "--library",
                "/lib",
                "--old-dir",
                "/old",
                "--quiet",
                "--verbose",
            ]
        )
    parser = build_parser()
    args = parser.parse_args(
        [
            "download",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--quiet",
        ]
    )
    assert args.quiet is True


def test_download_accepts_staging() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "download",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--staging",
            "/tmp/yt-emby",
        ]
    )
    assert args.staging == "/tmp/yt-emby"


def test_download_accepts_force_refetch() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "download",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--force-refetch",
        ]
    )
    assert args.force_refetch is True


def test_download_accepts_cookies_file() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "download",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--cookies",
            "cookies.txt",
        ]
    )
    assert args.cookies == "cookies.txt"
