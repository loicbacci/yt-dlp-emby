from yt_dlp_emby.extract import (
    episode_from_info,
    extract_playlist,
    extract_video,
    pick_avatar,
    pick_banner,
    pick_best_thumbnail,
    parse_channel_art,
    parse_playlist,
)


def test_parse_playlist_maps_channel_and_episodes() -> None:
    info = {
        "id": "PLtest",
        "title": "A Course",
        "description": "Playlist plot",
        "channel": "Example Channel",
        "channel_id": "UCabc",
        "thumbnails": [{"url": "https://img.example/pl.jpg", "width": 640}],
        "entries": [
            {
                "id": "vid1",
                "title": "Intro",
                "description": "First lesson",
                "upload_date": "20240101",
                "duration": 120.4,
                "filesize_approx": 1000,
                "playlist_index": 1,
                "thumbnail": "https://img.example/e1.jpg",
                "webpage_url": "https://www.youtube.com/watch?v=vid1",
            },
            {
                "id": "vid2",
                "title": "Next",
                "description": "Second",
                "upload_date": "20240102",
                "duration": 60,
                "filesize": 2000,
                "playlist_index": 2,
                "thumbnails": [{"url": "https://img.example/e2.jpg", "width": 320}],
            },
        ],
    }
    playlist = parse_playlist(info)
    assert playlist.playlist_id == "PLtest"
    assert playlist.title == "A Course"
    assert playlist.channel == "Example Channel"
    assert playlist.channel_id == "UCabc"
    assert playlist.thumbnail_url == "https://img.example/pl.jpg"
    assert [e.video_id for e in playlist.episodes] == ["vid1", "vid2"]
    assert playlist.episodes[0].playlist_index == 1
    assert playlist.episodes[0].upload_date == "20240101"
    assert playlist.episodes[0].thumbnail_url == "https://img.example/e1.jpg"
    assert playlist.episodes[1].filesize == 2000
    assert playlist.episodes[0].webpage_url == "https://www.youtube.com/watch?v=vid1"


def test_parse_playlist_webpage_url_from_flat_url() -> None:
    info = {
        "id": "PLtest",
        "title": "A Course",
        "channel": "Example Channel",
        "channel_id": "UCabc",
        "entries": [
            {"id": "vid1", "title": "Intro", "url": "https://www.youtube.com/watch?v=vid1"},
        ],
    }
    playlist = parse_playlist(info)
    assert playlist.episodes[0].webpage_url == "https://www.youtube.com/watch?v=vid1"


def test_parse_playlist_webpage_url_from_id() -> None:
    info = {
        "id": "PLtest",
        "title": "A Course",
        "channel": "Example Channel",
        "channel_id": "UCabc",
        "entries": [{"id": "vid1", "title": "Intro"}],
    }
    playlist = parse_playlist(info)
    assert playlist.episodes[0].webpage_url == "https://www.youtube.com/watch?v=vid1"


def test_extract_playlist_uses_flat_listing() -> None:
    captured: dict = {}

    def fake_extract(url: str, opts: dict) -> dict:
        captured.update(opts)
        return {
            "id": "PLx",
            "title": "Course",
            "channel": "Example",
            "channel_id": "UC1",
            "entries": [
                {"id": "vid1", "title": "Intro", "url": "https://www.youtube.com/watch?v=vid1"},
            ],
        }

    playlist = extract_playlist("https://example.invalid/playlist", extract_fn=fake_extract)
    assert captured.get("extract_flat") == "in_playlist"
    assert playlist.episodes[0].webpage_url.endswith("vid1")


def test_extract_video_does_not_use_flat_listing() -> None:
    captured: dict = {}

    def fake_extract(url: str, opts: dict) -> dict:
        captured.update(opts)
        return {"id": "vid1", "title": "Intro", "description": "Plot"}

    episode = extract_video(
        "https://www.youtube.com/watch?v=vid1",
        3,
        extract_fn=fake_extract,
    )
    assert "extract_flat" not in captured
    assert episode.playlist_index == 3


def test_episode_from_info_overrides_playlist_index() -> None:
    episode = episode_from_info(
        {
            "id": "vid1",
            "title": "Intro",
            "description": "Plot",
            "webpage_url": "https://www.youtube.com/watch?v=vid1",
        },
        playlist_index=4,
    )
    assert episode.video_id == "vid1"
    assert episode.playlist_index == 4
    assert episode.description == "Plot"


def test_parse_playlist_skips_none_entries_and_numbers_from_order() -> None:
    info = {
        "id": "PLtest",
        "title": "A Course",
        "channel": "Example Channel",
        "channel_id": "UCabc",
        "entries": [
            None,
            {"id": "vid1", "title": "Only", "playlist_index": None},
        ],
    }
    playlist = parse_playlist(info)
    assert len(playlist.episodes) == 1
    assert playlist.episodes[0].playlist_index == 1


def test_pick_avatar_prefers_uncropped() -> None:
    thumbs = [
        {"url": "https://img.example/small.jpg", "preference": 0},
        {"id": "avatar_uncropped", "url": "https://img.example/avatar.jpg", "preference": 1},
        {"id": "banner_uncropped", "url": "https://img.example/banner.jpg", "preference": -5},
    ]
    assert pick_avatar(thumbs) == "https://img.example/avatar.jpg"


def test_pick_banner_prefers_uncropped() -> None:
    thumbs = [
        {"id": "avatar_uncropped", "url": "https://img.example/avatar.jpg", "preference": 1},
        {"url": "https://img.example/banner-small.jpg", "preference": -10},
        {"id": "banner_uncropped", "url": "https://img.example/banner.jpg", "preference": -5},
    ]
    assert pick_banner(thumbs) == "https://img.example/banner.jpg"


def test_pick_banner_none_when_only_avatar() -> None:
    thumbs = [{"id": "avatar_uncropped", "url": "https://img.example/avatar.jpg", "preference": 1}]
    assert pick_banner(thumbs) is None


def test_parse_channel_art() -> None:
    info = {
        "id": "UCabc",
        "channel": "Example Channel",
        "channel_id": "UCabc",
        "description": "About the channel",
        "thumbnails": [
            {"id": "avatar_uncropped", "url": "https://img.example/avatar.jpg", "preference": 1},
            {"id": "banner_uncropped", "url": "https://img.example/banner.jpg", "preference": -5},
        ],
    }
    art = parse_channel_art(info)
    assert art.channel_id == "UCabc"
    assert art.avatar_url.endswith("avatar.jpg")
    assert art.banner_url.endswith("banner.jpg")
    assert art.description == "About the channel"


def test_pick_best_thumbnail_uses_largest_width() -> None:
    url = pick_best_thumbnail(
        [
            {"url": "https://img.example/a.jpg", "width": 120},
            {"url": "https://img.example/b.jpg", "width": 1920},
        ]
    )
    assert url == "https://img.example/b.jpg"
