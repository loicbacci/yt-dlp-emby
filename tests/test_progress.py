from io import StringIO

from yt_emby.progress import (
    DownloadProgress,
    format_bytes,
    format_extract_line,
    format_progress_line,
    parse_playlist_item,
    render_bar,
    strip_ansi,
)


def test_render_bar_is_fixed_width() -> None:
    bar = render_bar(50, width=10)
    assert len(bar) == 10
    assert bar.startswith("#")
    assert "-" in bar


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


def test_progress_hook_writes_carriage_return() -> None:
    stream = StringIO()
    bar = DownloadProgress(enabled=True, stream=stream)
    bar.hook(
        {
            "status": "downloading",
            "downloaded_bytes": 50,
            "total_bytes": 100,
            "speed": 1024,
            "eta": 1,
        }
    )
    output = stream.getvalue()
    assert output.startswith("\r")
    assert "50.0%" in output
    bar.hook({"status": "finished"})
    output = stream.getvalue()
    assert "Download complete" in output
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


def test_ytdlp_logger_updates_extract_progress() -> None:
    from yt_emby.progress import ExtractProgress, YtdlpLogger

    stream = StringIO()
    display = ExtractProgress(enabled=True, stream=stream)
    logger = YtdlpLogger(display)
    logger.debug("Extracting URL: https://www.youtube.com/playlist?list=x")
    assert "Connecting" in stream.getvalue()
    assert "(0s)" in stream.getvalue()
    logger.debug("[youtube] abc: Downloading webpage")
    assert "playlist page" in stream.getvalue()
    logger.debug("[download] Downloading item 4 of 20")
    assert "4/20" in stream.getvalue()
    logger.debug("[youtube] vid: Downloading webpage")
    assert stream.getvalue().count("4/20") >= 1
    logger.debug("[debug] ignored")

