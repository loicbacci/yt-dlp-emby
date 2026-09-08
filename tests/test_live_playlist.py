from __future__ import annotations

import pytest

from yt_emby.extract import extract_channel_art, extract_playlist

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
