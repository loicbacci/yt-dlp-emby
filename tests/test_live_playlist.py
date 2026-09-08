from __future__ import annotations

from pathlib import Path

import pytest

from yt_emby.config import resolve_settings
from yt_emby.download import LOW_RES_FORMAT
from yt_emby.extract import extract_channel_art, extract_playlist
from yt_emby.pipeline import run_download as pipeline_run

LIVE_PLAYLIST = "https://www.youtube.com/playlist?list=PLG49S3nxzAnl4QDVqK-hOnoqcSKEIDDuv"


pytestmark = pytest.mark.network


def test_live_playlist_metadata_first_two_videos() -> None:
    playlist = extract_playlist(LIVE_PLAYLIST, playlist_items="1:2")
    assert playlist.channel
    assert playlist.channel_id.startswith("UC")
    assert playlist.playlist_id
    assert playlist.title
    assert len(playlist.episodes) == 2
    for episode in playlist.episodes:
        assert episode.video_id
        assert episode.title
        assert episode.playlist_index in (1, 2)
        assert episode.thumbnail_url


def test_live_channel_art() -> None:
    playlist = extract_playlist(LIVE_PLAYLIST, playlist_items="1:1")
    art = extract_channel_art(playlist.channel_id)
    assert art.channel_id == playlist.channel_id
    assert art.avatar_url


def test_live_low_res_download_writes_emby_layout(tmp_path: Path) -> None:
    library = tmp_path / "library"
    old_dir = tmp_path / "old"
    settings = resolve_settings(
        library=str(library),
        old_dir=str(old_dir),
        environ={},
        cwd=tmp_path,
    )
    code = pipeline_run(
        LIVE_PLAYLIST,
        settings,
        format_selector=LOW_RES_FORMAT,
        playlist_items="1:1",
    )
    assert code == 0
    series_dirs = [p for p in library.iterdir() if p.is_dir()]
    assert len(series_dirs) == 1
    series = series_dirs[0]
    assert (series / "tvshow.nfo").is_file()
    assert (series / "poster.jpg").is_file()
    assert (series / ".yt-emby.json").is_file()
    season = series / "Season 01"
    assert (season / "season.nfo").is_file()
    videos = list(season.glob("*.mkv"))
    assert videos, "expected a remuxed mkv"
    assert any(path.name != "season.nfo" for path in season.glob("*.nfo"))
    thumbs = list(season.glob("*-thumb.jpg"))
    assert thumbs
    xml = (series / "tvshow.nfo").read_text(encoding="utf-8")
    assert "<lockdata>true</lockdata>" in xml
    assert "youtube" in xml
    assert "tmdbid" not in xml
