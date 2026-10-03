from yt_dlp_emby.dropout_manifest import DropoutRemap, DropoutSeason
from yt_dlp_emby.extract import DropoutListing
from yt_dlp_emby.server.series_discover import (
    ChannelDiscoverError,
    _playlist_url_from_entry,
    discover_youtube_sources,
    dropout_episode_rows,
    library_episode_status,
    merge_dropout_seasons,
)


def test_playlist_url_from_entry_ignores_videos() -> None:
    assert (
        _playlist_url_from_entry({"_type": "video", "url": "https://www.youtube.com/watch?v=abc"})
        is None
    )
    assert (
        _playlist_url_from_entry(
            {
                "_type": "playlist",
                "url": "https://www.youtube.com/playlist?list=PLx",
            }
        )
        == "https://www.youtube.com/playlist?list=PLx"
    )


def test_channel_extract_keeps_playlists_only() -> None:
    def extract(_url: str):
        return {
            "entries": [
                {"_type": "video", "url": "https://www.youtube.com/watch?v=aaa"},
                {
                    "_type": "playlist",
                    "url": "https://www.youtube.com/playlist?list=PLone",
                    "title": "Season 1",
                },
            ]
        }

    sources = discover_youtube_sources(
        "https://www.youtube.com/@example",
        cookiefile=None,
        extract_channel=extract,
    )
    assert len(sources) == 1
    assert "list=PLone" in sources[0]["url"]
    assert sources[0]["seasons"][0]["to_season"] == 1


def test_channel_extract_failure_raises() -> None:
    def extract(_url: str):
        raise RuntimeError("login required")

    try:
        discover_youtube_sources(
            "https://www.youtube.com/@example",
            cookiefile=None,
            extract_channel=extract,
        )
    except ChannelDiscoverError as exc:
        assert "login required" in exc.message
    else:
        raise AssertionError("expected ChannelDiscoverError")


def test_library_episode_status() -> None:
    on_disk = {(1, 1)}
    assert library_episode_status(True, 1, 1, on_disk) == "skipped"
    assert library_episode_status(False, None, None, on_disk) == "unmapped"
    assert library_episode_status(False, 1, 1, on_disk) == "downloaded"
    assert library_episode_status(False, 1, 2, on_disk) == "missing"


def test_dropout_episode_rows_mark_disk_status() -> None:
    season = DropoutSeason(dropout=1)
    listings = [
        DropoutListing("https://watch.dropout.tv/videos/a", "Pilot", 1),
        DropoutListing("https://watch.dropout.tv/videos/b", "Two", 2),
    ]
    rows = dropout_episode_rows(season, listings, on_disk={(1, 1)})
    assert rows[0]["status"] == "downloaded"
    assert rows[1]["status"] == "missing"


def test_merge_dropout_seasons_preserves_custom_mappings_and_vanished_seasons() -> None:
    custom = DropoutSeason(
        dropout=28,
        url="https://watch.dropout.tv/custom-season-28",
        to_season=27,
        enabled=True,
        title="Custom title",
        only_episodes=(2, 5),
        remap=(DropoutRemap(5, to_season=27, to_episode=9, title="Special cut"),),
    )
    vanished = DropoutSeason(dropout=4, url="https://watch.dropout.tv/old", enabled=False)
    merged = merge_dropout_seasons(
        (custom, vanished),
        [
            {"dropout": 28, "url": "https://watch.dropout.tv/28", "to_season": 28},
            {"dropout": 29, "url": "https://watch.dropout.tv/29", "to_season": 29},
        ],
    )

    assert merged[0] == custom
    assert merged[1].dropout == 29
    assert merged[1].url == "https://watch.dropout.tv/29"
    assert merged[1].to_season == 29
    assert merged[1].enabled is False
    assert merged[2] == vanished
