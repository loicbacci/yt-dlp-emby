from yt_emby.extract import (
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
