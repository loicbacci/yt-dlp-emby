from io import StringIO

import pytest

from yt_dlp_emby.log import (
    format_duration,
    format_elapsed,
    format_plan_counts,
    format_run_summary,
    format_unit_plan,
)
from yt_dlp_emby.progress import (
    DownloadProgress,
    estimate_media_bytes,
    format_bytes,
    format_copy_line,
    format_extract_line,
    format_progress_line,
    format_size_estimate,
    parse_playlist_item,
    render_bar,
    stream_label,
    strip_ansi,
)
from yt_dlp_emby.style import visible_len


def test_render_bar_is_fixed_width() -> None:
    bar = render_bar(50, width=10)
    assert len(bar) == 10
    assert bar.startswith("#")
    assert "-" in bar
    fancy = render_bar(50, width=10, fancy=True, color=True)
    assert visible_len(fancy) == 10
    assert "█" in fancy
    assert "░" in fancy
    assert "\033[" in fancy


def test_format_bytes() -> None:
    assert format_bytes(500) == "500.0B"
    assert format_bytes(2048).endswith("KiB")
    assert format_bytes(1024 * 1024).endswith("MiB")


def test_progress_line_with_total() -> None:
    line = format_progress_line(
        {
            "status": "downloading",
            "downloaded_bytes": 50 * 1024 * 1024,
            "total_bytes": 100 * 1024 * 1024,
            "speed": 2 * 1024 * 1024,
            "eta": 25,
        }
    )
    assert "50.0%" in line
    assert "ETA 00:25" in line
    assert "MiB/s" in line


def test_progress_line_without_total() -> None:
    line = format_progress_line(
        {
            "status": "downloading",
            "downloaded_bytes": 4096,
            "speed": 1024,
        }
    )
    assert "%" not in line
    assert "KiB" in line


def test_progress_line_includes_stream_label() -> None:
    line = format_progress_line(
        {
            "downloaded_bytes": 50,
            "total_bytes": 100,
            "speed": 1024,
            "eta": 1,
        },
        label="video",
    )
    assert line.startswith("video  ")
    assert "50.0%" in line


def test_stream_label_video_audio_subs() -> None:
    assert (
        stream_label({"info_dict": {"vcodec": "avc1", "acodec": "none"}}) == "video"
    )
    assert (
        stream_label({"info_dict": {"vcodec": "none", "acodec": "mp4a.40.2"}}) == "audio"
    )
    assert stream_label({"filename": "ep.en.srt", "info_dict": {"language": "en"}}) == "en.srt"
    assert stream_label({"filename": "ep.mkv"}) == "download"


def test_format_copy_line() -> None:
    line = format_copy_line(50 * 1024 * 1024, 100 * 1024 * 1024, width=10)
    assert line.startswith("copy  ")
    assert "50.0%" in line


def test_progress_hook_writes_carriage_return() -> None:
    stream = StringIO()
    bar = DownloadProgress(enabled=True, stream=stream, live=True)
    bar.hook(
        {
            "status": "downloading",
            "downloaded_bytes": 50,
            "total_bytes": 100,
            "speed": 1024,
            "eta": 1,
            "info_dict": {"vcodec": "avc1", "acodec": "none"},
        }
    )
    output = stream.getvalue()
    assert output.startswith("\r")
    assert "video" in output
    assert "50.0%" in output
    bar.hook(
        {
            "status": "finished",
            "info_dict": {"vcodec": "avc1", "acodec": "none"},
        }
    )
    assert "video  complete" in stream.getvalue()
    bar.close()
    assert stream.getvalue().endswith("\n")


def test_progress_non_tty_writes_newlines() -> None:
    stream = StringIO()
    bar = DownloadProgress(enabled=True, stream=stream, live=False)
    bar.hook(
        {
            "status": "downloading",
            "downloaded_bytes": 50,
            "total_bytes": 100,
            "speed": 1024,
            "eta": 1,
            "info_dict": {"vcodec": "none", "acodec": "mp4a.40.2"},
        }
    )
    output = stream.getvalue()
    assert "\r" not in output
    assert "audio" in output
    assert output.endswith("\n")


def test_parse_playlist_item_strips_ansi() -> None:
    assert parse_playlist_item("[download] Downloading item 3 of 121") == (3, 121)
    colored = "Downloading item \x1b[0;32m12\x1b[0m of \x1b[0;32m121\x1b[0m"
    assert parse_playlist_item(colored) == (12, 121)
    assert parse_playlist_item("nope") is None
    assert "\x1b" not in strip_ansi(colored)


def test_extract_line() -> None:
    line = format_extract_line(12, 121, width=10)
    assert "12/121" in line
    assert "Listing playlist" in line
    season = format_extract_line(3, 8, width=10, listing="season")
    assert "Listing season" in season


def test_ytdlp_logger_updates_extract_progress() -> None:
    from yt_dlp_emby.progress import ExtractProgress, YtdlpLogger

    stream = StringIO()
    display = ExtractProgress(enabled=True, stream=stream, live=True)
    logger = YtdlpLogger(display)
    logger.debug("Extracting URL: https://www.youtube.com/playlist?list=x")
    assert "Connecting to YouTube" in stream.getvalue()
    assert "(0s)" in stream.getvalue()
    logger.debug("[youtube] abc: Downloading webpage")
    assert "playlist page" in stream.getvalue()
    logger.debug("[download] Downloading item 4 of 20")
    assert "4/20" in stream.getvalue()
    logger.debug("[youtube] vid: Downloading webpage")
    assert stream.getvalue().count("4/20") >= 1
    logger.debug("[debug] ignored")


def test_ytdlp_logger_emits_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    from yt_dlp_emby.progress import ExtractProgress, YtdlpLogger

    logger = YtdlpLogger(ExtractProgress(enabled=False), emit_warnings=True, emit_errors=True)
    logger.warning("HTTP Error 403: Forbidden")
    logger.error("Unable to download webpage")
    err = capsys.readouterr().err
    assert "warning: HTTP Error 403: Forbidden" in strip_ansi(err)
    assert "error: Unable to download webpage" in strip_ansi(err)
    assert logger.warnings == ["HTTP Error 403: Forbidden"]
    assert logger.errors == ["Unable to download webpage"]


def test_ytdlp_logger_dropout_site() -> None:
    from yt_dlp_emby.progress import ExtractProgress, YtdlpLogger

    stream = StringIO()
    display = ExtractProgress(
        enabled=True, stream=stream, live=True, listing="season", site="Dropout"
    )
    logger = YtdlpLogger(display)
    logger.debug("Extracting URL: https://watch.dropout.tv/x/season:1")
    assert "Connecting to Dropout" in stream.getvalue()
    assert "YouTube" not in stream.getvalue()
    logger.debug("[dropout] Downloading webpage")
    assert "season page" in stream.getvalue()
    logger.debug("[download] Downloading item 2 of 9")
    assert "Listing season" in stream.getvalue()


def test_run_summary_and_plan_counts() -> None:
    assert strip_ansi(format_run_summary(downloaded=3, skipped=12, failed=1)) == (
        "Done  downloaded=3  skipped=12  failed=1"
    )
    assert strip_ansi(format_run_summary(downloaded=3, skipped=12, dry_run=True)) == (
        "Done  dry-run  download=3  skip=12"
    )
    assert strip_ansi(format_plan_counts({"add": 12, "refresh": 3})) == "12 add  3 refresh"
    assert format_plan_counts({}) == "nothing to do"
    assert format_duration(12) == "12s"
    assert format_duration(84) == "1m24s"
    assert format_duration(3725) == "1h02m"
    assert format_elapsed(0.004) == "4ms"
    assert format_elapsed(0.012) == "12ms"
    assert format_elapsed(1.4) == "1.4s"
    assert format_elapsed(12) == "12s"
    line = strip_ansi(
        format_unit_plan(
            "season 1",
            dest="Season 1",
            skip=12,
            download=2,
            extras={"rename": 1},
            listing_source="listed",
            listing_seconds=0.004,
            disk_seconds=1.4,
        )
    )
    assert line.startswith("  season 1 → Season 1")
    assert "12 skip" in line
    assert "2 download" in line
    assert "1 rename" in line
    assert line.endswith("listed  1.4s")
    sized = strip_ansi(
        format_unit_plan(
            "season 1", dest="Season 1", skip=0, download=2, download_bytes=2_250_000_000
        )
    )
    assert "2 download" in sized
    assert "~2.1GiB" in sized
    assert format_size_estimate(None) is None
    assert estimate_media_bytes(filesize=1000) == 1000
    assert estimate_media_bytes(filesize=1000, duration=3600) == 1000
    assert estimate_media_bytes(duration=3600) == 2_250_000_000
    assert estimate_media_bytes() is None
    debug = strip_ansi(
        format_unit_plan(
            "season 1",
            dest="Season 1",
            skip=12,
            download=0,
            listing_source="listed",
            listing_seconds=0.004,
            disk_seconds=1.4,
            debug=True,
        )
    )
    assert "listed 4ms  disk 1.4s" in debug
    assert "interrupted" in strip_ansi(
        format_run_summary(
            downloaded=2, skipped=5, failed=0, remaining=9, interrupted=True, elapsed=181
        )
    )
