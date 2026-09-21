from pathlib import Path

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
            "download",
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
            "download",
            "--manifest",
            "dropout.yaml",
            "--force",
            "--dry-run",
        ]
    )
    assert args.command == "dropout"
    assert args.dropout_command == "download"
    assert args.manifest == "dropout.yaml"
    assert args.force is True
    assert args.dry_run is True


def test_dropout_requires_verb() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["dropout"])


def test_dropout_rejects_layout_flag() -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["dropout", "download", "--layout"])


def test_dropout_layout_verb() -> None:
    parser = build_parser()
    args = parser.parse_args(["dropout", "layout"])
    assert args.dropout_command == "layout"
    with pytest.raises(SystemExit):
        parser.parse_args(["dropout", "layout", "--force"])


def test_dropout_check_verb() -> None:
    parser = build_parser()
    args = parser.parse_args(["dropout", "check", "--series", "Game Changer"])
    assert args.dropout_command == "check"
    assert args.series_filter == ["Game Changer"]
    with pytest.raises(SystemExit):
        parser.parse_args(["dropout", "check", "--force"])


def test_dropout_help_explains_verbs(capsys) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["dropout", "--help"])
    out = capsys.readouterr().out
    assert "download" in out
    assert "layout" in out
    assert "check" in out
    assert "remap" in out.lower() or "grouped" in out.lower()
    assert "Sonarr" in out or "missing" in out.lower()


def test_top_level_help_mentions_dropout_verbs() -> None:
    help_text = build_parser().format_help()
    assert "download" in help_text
    assert "layout" in help_text
    assert "check" in help_text


def test_dropout_accepts_force_refetch() -> None:
    parser = build_parser()
    args = parser.parse_args(
        ["dropout", "download", "--manifest", "dropout.yaml", "--force-refetch"]
    )
    assert args.force_refetch is True


def test_dropout_accepts_debug() -> None:
    parser = build_parser()
    debug = parser.parse_args(["dropout", "download", "--debug"])
    assert debug.debug is True
    assert debug.verbose is False
    vv = parser.parse_args(["dropout", "download", "-vv"])
    assert vv.debug is True
    assert vv.verbose is False
    both = parser.parse_args(["dropout", "download", "-v", "--debug"])
    assert both.verbose is True
    assert both.debug is True


def test_youtube_accepts_debug() -> None:
    parser = build_parser()
    debug = parser.parse_args(["youtube", "--debug"])
    assert debug.debug is True
    assert debug.verbose is False
    vv = parser.parse_args(["youtube", "-vv"])
    assert vv.debug is True
    both = parser.parse_args(["youtube", "-v", "--debug"])
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
            "download",
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


def test_cli_check_passes_sonarr_flags() -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "dropout",
            "check",
            "--sonarr-url",
            "http://localhost:8989",
            "--sonarr-api-key",
            "secret",
            "--force-refetch",
        ]
    )
    assert args.dropout_command == "check"
    assert args.sonarr_url == "http://localhost:8989"
    assert args.sonarr_api_key == "secret"
    assert args.force_refetch is True


def test_cli_check_does_not_require_cookies(tmp_path, monkeypatch) -> None:
    from yt_dlp_emby.cli import run_dropout

    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    monkeypatch.setenv("YT_DLP_EMBY_FFMPEG", str(ffmpeg))
    path = tmp_path / "dropout.yaml"
    path.write_text(
        f"""
library: {tmp_path / "lib"}
old_dir: {tmp_path / "old"}
series:
  - name: No Id Show
    path: No Id Show
    url: https://watch.dropout.tv/no-id
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    args = build_parser().parse_args(["dropout", "check", "--manifest", str(path)])
    assert run_dropout(args) == 0


def test_youtube_manifest_honors_config_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.cli import run_download

    manifest = tmp_path / "youtube.yaml"
    manifest.write_text(
        """
series:
  - name: Example Channel
    playlists:
      - url: https://example.invalid/playlist
""",
        encoding="utf-8",
    )
    config = tmp_path / "alt.toml"
    config.write_text(
        f'[fallback]\nlibrary = "{tmp_path / "lib"}"\nold_dir = "{tmp_path / "old"}"\n',
        encoding="utf-8",
    )
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    captured: dict = {}

    def fake_run(manifest_obj, settings, format_selector=None):
        captured["config"] = settings.config_path
        return 0

    monkeypatch.setattr("yt_dlp_emby.pipeline.run_youtube_manifest", fake_run)
    monkeypatch.setenv("YT_DLP_EMBY_FFMPEG", str(ffmpeg))
    args = build_parser().parse_args(
        [
            "youtube",
            "--manifest",
            str(manifest),
            "--config",
            str(config),
            "--dry-run",
        ]
    )
    assert run_download(args) == 0
    assert captured["config"] == config


def test_dropout_honors_config_flag(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_dlp_emby.cli import run_dropout

    manifest = tmp_path / "dropout.yaml"
    manifest.write_text(
        """
series:
  - name: Show
    path: Show
    url: https://watch.dropout.tv/x
    seasons:
      - dropout: 1
""",
        encoding="utf-8",
    )
    config = tmp_path / "alt.toml"
    config.write_text(
        f'[fallback]\nlibrary = "{tmp_path / "lib"}"\nold_dir = "{tmp_path / "old"}"\n',
        encoding="utf-8",
    )
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    captured: dict = {}

    def fake_run(manifest_obj, settings, force=False, create=False, format_selector=None):
        captured["config"] = settings.config_path
        return 0

    monkeypatch.setattr("yt_dlp_emby.dropout.run_dropout", fake_run)
    monkeypatch.setenv("YT_DLP_EMBY_FFMPEG", str(ffmpeg))
    args = build_parser().parse_args(
        [
            "dropout",
            "download",
            "--manifest",
            str(manifest),
            "--config",
            str(config),
            "--dry-run",
        ]
    )
    assert run_dropout(args) == 0
    assert captured["config"] == config
