from pathlib import Path

from yt_emby.library import (
    EpisodeRecord,
    LibraryIndex,
    PlaylistRecord,
    assign_season,
    episode_stem,
    episode_title_from_filename,
    find_episode_mkv,
    load_index,
    save_index,
    sanitize_filename,
    season_folder_name,
    series_dir,
    titles_match,
)


def test_sanitize_filename_strips_illegal_chars() -> None:
    assert "/" not in sanitize_filename("a/b")
    assert ":" not in sanitize_filename("Season: 1")
    assert sanitize_filename("  hello  ") == "hello"
    assert sanitize_filename("") == "untitled"


def test_series_and_season_paths(tmp_path: Path) -> None:
    series = series_dir(tmp_path, "Example Channel")
    assert series == tmp_path / "Example Channel"
    assert season_folder_name(1) == "Season 1"
    assert season_folder_name(3) == "Season 3"
    assert season_folder_name(12) == "Season 12"


def test_episode_stem_uses_emby_pattern() -> None:
    name = episode_stem("Example Channel", 1, 2, "Pilot: Hello")
    assert name.startswith("Example Channel - S01E02 - ")
    assert ":" not in name


def test_titles_match_ignores_case_and_punctuation() -> None:
    assert titles_match("Welcome to the Wastes", "welcome to the wastes")
    assert titles_match("Hello, World!", "Hello World")
    assert not titles_match("Old Title", "Welcome to the Wastes")
    assert episode_title_from_filename(
        "Dimension 20 - S27E01 - welcome to the wastes.mkv"
    ) == "welcome to the wastes"


def test_find_episode_mkv_matches_code_not_title(tmp_path: Path) -> None:
    season = tmp_path / "Season 27"
    season.mkdir()
    old = season / "Dimension 20 - S27E01 - Old Title.mkv"
    old.write_bytes(b"x")
    found = find_episode_mkv(season, 27, 1)
    assert found == old
    assert find_episode_mkv(season, 27, 2) is None


def test_assign_season_sticky_then_next() -> None:
    index = LibraryIndex(channel_id="UC1", channel_name="Example")
    assert assign_season(index, "PL_a", None) == 1
    index.playlists["PL_a"] = PlaylistRecord(season=1, title="A", playlist_id="PL_a")
    assert assign_season(index, "PL_a", None) == 1
    assert assign_season(index, "PL_b", None) == 2
    assert assign_season(index, "PL_c", 5) == 5


def test_index_roundtrip(tmp_path: Path) -> None:
    series = tmp_path / "Example Channel"
    series.mkdir()
    index = LibraryIndex(
        channel_id="UC1",
        channel_name="Example Channel",
        playlists={
            "PLa": PlaylistRecord(
                playlist_id="PLa",
                season=1,
                title="Course",
                description="Plot",
                episodes={
                    "vid1": EpisodeRecord(
                        video_id="vid1",
                        episode=1,
                        title="Intro",
                        duration=120,
                        filesize=1000,
                        upload_date="20240101",
                        basename="Example Channel - S01E01 - Intro",
                    )
                },
            )
        },
    )
    save_index(series, index)
    loaded = load_index(series)
    assert loaded.channel_id == "UC1"
    assert loaded.playlists["PLa"].season == 1
    assert loaded.playlists["PLa"].episodes["vid1"].basename.endswith("Intro")
