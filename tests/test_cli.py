import pytest

from yt_dlp_emby.cli import build_parser


def test_download_requires_url() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "youtube",
            "https://www.youtube.com/playlist?list=PLAYLIST_ID",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--dry-run",
        ]
    )
    assert args.command == "youtube"
    assert args.url.endswith("PLAYLIST_ID")
    assert args.dry_run is True
    assert args.library == "/lib"
    assert args.old_dir == "/old"


def test_doctor_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "doctor",
            "--cookies",
            "cookies.txt",
            "--staging",
            "/tmp/yt-dlp-emby",
            "--library",
            "/lib",
        ]
    )
    assert args.command == "doctor"
    assert args.cookies == "cookies.txt"
    assert args.staging == "/tmp/yt-dlp-emby"
    assert args.library == "/lib"


def test_download_accepts_season_and_cookies() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "youtube",
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
            "youtube",
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
                "youtube",
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
            "youtube",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--quiet",
        ]
    )
    assert args.quiet is True


def test_silent_is_exclusive_with_quiet() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "youtube",
                "https://example.invalid/watch?v=abc",
                "--library",
                "/lib",
                "--old-dir",
                "/old",
                "--quiet",
                "--silent",
            ]
        )
    args = parser.parse_args(
        [
            "dropout",
            "--manifest",
            "dropout.yaml",
            "--silent",
        ]
    )
    assert args.silent is True
    assert args.quiet is False


def test_download_accepts_staging() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "youtube",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--staging",
            "/tmp/yt-dlp-emby",
        ]
    )
    assert args.staging == "/tmp/yt-dlp-emby"


def test_download_accepts_force_refetch() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "youtube",
            "https://example.invalid/watch?v=abc",
            "--library",
            "/lib",
            "--old-dir",
            "/old",
            "--force-refetch",
        ]
    )
    assert args.force_refetch is True


def test_youtube_url_is_optional() -> None:
    parser = build_parser()
    args = parser.parse_args(["youtube", "--dry-run"])
    assert args.command == "youtube"
    assert args.url is None
    assert args.dry_run is True


def test_youtube_accepts_manifest_and_series() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "youtube",
            "--manifest",
            "youtube.yaml",
            "--series",
            "Example Channel",
            "--dry-run",
        ]
    )
    assert args.manifest == "youtube.yaml"
    assert args.series_filter == ["Example Channel"]
    assert args.url is None


def test_download_accepts_cookies_file() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "youtube",
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


def test_download_subcommand_removed() -> None:
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
            ]
        )


def test_dropout_accepts_manifest_and_force() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "dropout",
            "--manifest",
            "dropout.yaml",
            "--force",
            "--dry-run",
        ]
    )
    assert args.command == "dropout"
    assert args.manifest == "dropout.yaml"
    assert args.force is True
    assert args.dry_run is True


def test_dropout_accepts_force_refetch() -> None:
    parser = build_parser()
    args = parser.parse_args(["dropout", "--manifest", "dropout.yaml", "--force-refetch"])
    assert args.force_refetch is True


def test_dropout_accepts_debug() -> None:
    parser = build_parser()
    debug = parser.parse_args(["dropout", "--debug"])
    assert debug.debug is True
    assert debug.verbose is False
    vv = parser.parse_args(["dropout", "-vv"])
    assert vv.debug is True
    assert vv.verbose is False
    both = parser.parse_args(["dropout", "-v", "--debug"])
    assert both.verbose is True
    assert both.debug is True


def test_bench_subcommand() -> None:
    parser = build_parser()
    args = parser.parse_args(["bench", "--size", "64M", "--dest", "/mnt/share"])
    assert args.command == "bench"
    assert args.size == "64M"
    assert args.dest == "/mnt/share"


def test_dropout_accepts_series_season_create() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "dropout",
            "--series",
            "Dimension 20",
            "--season",
            "28",
            "--season",
            "29",
            "--create",
        ]
    )
    assert args.series_filter == ["Dimension 20"]
    assert args.season_filter == [28, 29]
    assert args.create is True
