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


def test_merge_dropout_seasons_preserves_custom_mapping_and_adds_without_removing() -> None:
    original = DropoutSeason(
        dropout=1,
        url="https://watch.dropout.tv/show/season:1",
        to_season=7,
        remap=(DropoutRemap(dropout_episode=3, to_season=0, to_episode=4, title="Special"),),
        only_episodes=(3, 4),
        enabled=False,
        title="My season name",
    )
    no_longer_discovered = DropoutSeason(dropout=4, to_season=12, title="Keep this season")

    merged = merge_dropout_seasons(
        (original, no_longer_discovered),
        [
            {
                "dropout": 1,
                "url": "https://watch.dropout.tv/show/season:1?updated=1",
                "to_season": 1,
                "enabled": True,
            },
            {"dropout": 2, "url": "https://watch.dropout.tv/show/season:2", "to_season": 2},
        ],
    )

    assert [season.dropout for season in merged] == [1, 4, 2]
    assert merged[0] == DropoutSeason(
        dropout=1,
        url="https://watch.dropout.tv/show/season:1?updated=1",
        to_season=7,
        remap=original.remap,
        only_episodes=(3, 4),
        enabled=False,
        title="My season name",
    )
    assert merged[1] == no_longer_discovered
    assert merged[2].to_season == 2


def test_dropout_episode_rows_mark_disk_status() -> None:
    season = DropoutSeason(dropout=1)
    listings = [
        DropoutListing("https://watch.dropout.tv/videos/a", "Pilot", 1),
        DropoutListing("https://watch.dropout.tv/videos/b", "Two", 2),
    ]
    rows = dropout_episode_rows(season, listings, on_disk={(1, 1)})
    assert rows[0]["status"] == "downloaded"
    assert rows[1]["status"] == "missing"
