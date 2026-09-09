from pathlib import Path

from yt_emby.cache import (
    LEGACY_DROPOUT_CACHE_FILENAME,
    dropout_cache_path,
    dropout_listings_from_cache,
    dropout_listings_to_cache,
    episode_from_cache,
    episode_to_cache,
    hydrate_playlist,
    load_cache,
    load_dropout_season_cache,
    migrate_dropout_season_cache,
    save_cache,
    save_dropout_season_cache,
)
from yt_emby.extract import DropoutListing, EpisodeInfo, PlaylistInfo


def _listing(**kwargs: object) -> EpisodeInfo:
    return EpisodeInfo(
        video_id="vid1",
        title="Intro",
        description="",
        playlist_index=1,
        **kwargs,  # type: ignore[arg-type]
    )


def test_cache_roundtrip(tmp_path: Path) -> None:
    series = tmp_path / "Show"
    episode = EpisodeInfo(
        video_id="vid1",
        title="Intro",
        description="Plot",
        playlist_index=1,
        upload_date="20240101",
        duration=120,
        filesize=1000,
        thumbnail_url="https://img.example/e.jpg",
        webpage_url="https://www.youtube.com/watch?v=vid1",
    )
    save_cache(series, {episode.video_id: episode_to_cache(episode)})
    loaded = load_cache(series)
    merged = episode_from_cache(_listing(), loaded["vid1"])
    assert merged.description == "Plot"
    assert merged.upload_date == "20240101"
    assert merged.playlist_index == 1
    assert merged.title == "Intro"


def test_hydrate_uses_cache_unless_forced() -> None:
    playlist = PlaylistInfo(
        playlist_id="PLa",
        title="Course",
        description="",
        channel="Example",
        channel_id="UC1",
        thumbnail_url=None,
        episodes=[_listing()],
    )
    cache = {"vid1": {"title": "Intro", "description": "From cache"}}
    hydrated = hydrate_playlist(playlist, cache, force_refetch=False)
    assert hydrated.episodes[0].description == "From cache"
    skipped = hydrate_playlist(playlist, cache, force_refetch=True)
    assert skipped.episodes[0].description == ""


def test_hydrate_keeps_live_listing_title() -> None:
    playlist = PlaylistInfo(
        playlist_id="PLa",
        title="Course",
        description="",
        channel="Example",
        channel_id="UC1",
        thumbnail_url=None,
        episodes=[_listing()],
    )
    cache = {"vid1": {"title": "Old cached title", "description": "From cache"}}
    hydrated = hydrate_playlist(playlist, cache, force_refetch=False)
    assert hydrated.episodes[0].title == "Intro"
    assert hydrated.episodes[0].description == "From cache"


def test_dropout_season_cache_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "cache" / "dropout.json"
    listings = [
        DropoutListing(
            url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
            title="Welcome to the Wastes",
            dropout_episode=1,
        )
    ]
    page = "https://watch.dropout.tv/x/season:28"
    save_dropout_season_cache(path, {page: dropout_listings_to_cache(listings)})
    loaded = load_dropout_season_cache(path)
    restored = dropout_listings_from_cache(loaded[page])
    assert restored == listings
    assert path.is_file()
    assert dropout_listings_from_cache([]) is None
    assert dropout_listings_from_cache([{"url": "https://x", "title": "", "dropout_episode": 1}]) is None


def test_dropout_cache_path_next_to_manifest(tmp_path: Path) -> None:
    manifest = tmp_path / "shows" / "dropout.yaml"
    assert dropout_cache_path(manifest) == tmp_path / "shows" / "cache" / "dropout.json"
    assert dropout_cache_path(None, cwd=tmp_path) == tmp_path / "cache" / "dropout.json"


def test_migrate_dropout_cache_from_library(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    library.mkdir()
    dest = tmp_path / "cache" / "dropout.json"
    legacy = library / LEGACY_DROPOUT_CACHE_FILENAME
    listings = [
        DropoutListing(
            url="https://watch.dropout.tv/x/videos/welcome-to-the-wastes",
            title="Welcome to the Wastes",
            dropout_episode=1,
        )
    ]
    save_dropout_season_cache(legacy, {"https://x/season:28": dropout_listings_to_cache(listings)})
    moved = migrate_dropout_season_cache(dest, library)
    assert moved == legacy
    assert dest.is_file()
    assert not legacy.exists()
    loaded = load_dropout_season_cache(dest)
    assert dropout_listings_from_cache(loaded["https://x/season:28"]) == listings


def test_migrate_dropout_cache_keeps_new_and_removes_legacy(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    library.mkdir()
    dest = tmp_path / "cache" / "dropout.json"
    dest.parent.mkdir()
    dest.write_text('{"seasons": {"new": []}}\n', encoding="utf-8")
    legacy = library / LEGACY_DROPOUT_CACHE_FILENAME
    legacy.write_text('{"seasons": {"old": []}}\n', encoding="utf-8")
    moved = migrate_dropout_season_cache(dest, library)
    assert moved == legacy
    assert dest.read_text(encoding="utf-8") == '{"seasons": {"new": []}}\n'
    assert not legacy.exists()


def test_migrate_dropout_cache_noop_without_legacy(tmp_path: Path) -> None:
    library = tmp_path / "lib"
    library.mkdir()
    dest = tmp_path / "cache" / "dropout.json"
    assert migrate_dropout_season_cache(dest, library) is None
    assert not dest.exists()
