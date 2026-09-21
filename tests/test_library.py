from pathlib import Path

import pytest

from yt_dlp_emby.library import (
    EpisodeRecord,
    LibraryIndex,
    PlaylistRecord,
    assign_season,
    episode_stem,
    episode_title_from_filename,
    find_episode_mkv,
    index_episode_mkvs,
    load_index,
    sanitize_filename,
    save_index,
    season_dir,
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
    assert season_dir(series, 1) == series / "Season 1"


def test_season_dir_reuses_padded_folder(tmp_path: Path) -> None:
    series = tmp_path / "Show"
    padded = series / "Season 01"
    padded.mkdir(parents=True)
    assert season_dir(series, 1) == padded
    assert season_dir(series, 0) == series / "Specials"


def test_episode_stem_uses_emby_pattern() -> None:
    name = episode_stem("Example Channel", 1, 2, "Pilot: Hello")
    assert name.startswith("Example Channel - S01E02 - ")
    assert ":" not in name


def test_titles_match_ignores_case_and_punctuation() -> None:
    assert titles_match("Welcome to the Wastes", "welcome to the wastes")
    assert titles_match("Hello, World!", "Hello World")
    assert not titles_match("Old Title", "Welcome to the Wastes")
    assert (
        episode_title_from_filename("Dimension 20 - S27E01 - welcome to the wastes.mkv")
        == "welcome to the wastes"
    )


def test_find_episode_mkv_matches_code_not_title(tmp_path: Path) -> None:
    season = tmp_path / "Season 27"
    season.mkdir()
    old = season / "Dimension 20 - S27E01 - Old Title.mkv"
    old.write_bytes(b"x")
    found = find_episode_mkv(season, 27, 1)
    assert found == old
    assert find_episode_mkv(season, 27, 2) is None


def test_index_episode_mkvs_maps_codes(tmp_path: Path) -> None:
    season = tmp_path / "Season 27"
    season.mkdir()
    first = season / "Dimension 20 - S27E01 - Old Title.mkv"
    second = season / "Dimension 20 - S27E02 - Next.mkv"
    first.write_bytes(b"x")
    second.write_bytes(b"x")
    indexed = index_episode_mkvs(season)
    assert indexed[(27, 1)] == first
    assert indexed[(27, 2)] == second
    specials = tmp_path / "Specials"
    specials.mkdir()
    special = specials / "Dimension 20 - S00E70 - Special.mkv"
    special.write_bytes(b"x")
    assert index_episode_mkvs(specials)[(0, 70)] == special
    assert index_episode_mkvs(tmp_path / "missing") == {}


def test_index_episode_mkvs_ignores_temp_mkv(tmp_path: Path) -> None:
    season = tmp_path / "Season 13"
    season.mkdir()
    temp = season / "Dimension 20 - S13E08 - Wallops at Swallop's.temp.mkv"
    real = season / "Dimension 20 - S13E08 - Wallops at Swallop's.mkv"
    temp.write_bytes(b"partial")
    real.write_bytes(b"final")
    indexed = index_episode_mkvs(season)
    assert indexed[(13, 8)] == real


def test_index_episode_mkvs_keeps_titles_with_periods(tmp_path: Path) -> None:
    season = tmp_path / "Season 3"
    season.mkdir()
    episode = season / "Dimension 20 - S03E17 - Times Squaremageddon Pt. 2.mkv"
    episode.write_bytes(b"x")
    assert index_episode_mkvs(season)[(3, 17)] == episode


def test_index_episode_mkvs_matches_sxxexx_anywhere(tmp_path: Path) -> None:
    season = tmp_path / "Season 3"
    season.mkdir()
    episode = season / "S03E17 Times Squaremageddon Pt. 2.mkv"
    episode.write_bytes(b"x")
    assert index_episode_mkvs(season)[(3, 17)] == episode
    assert find_episode_mkv(season, 3, 17) == episode


def test_index_episode_mkvs_prefers_larger_duplicate(tmp_path: Path) -> None:
    season = tmp_path / "Season 1"
    season.mkdir()
    small = season / "Show - S01E01 - A.mkv"
    large = season / "Show - S01E01 - Z.mkv"
    small.write_bytes(b"x")
    large.write_bytes(b"x" * 32)
    tmp = season / ".__yt_dlp_emby_tmp__Show - S01E01 - A.mkv"
    tmp.write_bytes(b"stale")
    indexed = index_episode_mkvs(season)
    assert indexed[(1, 1)] == large


def test_series_relpath_rejects_traversal(tmp_path: Path) -> None:
    from yt_dlp_emby.library import series_library_path, series_relpath

    with pytest.raises(ValueError, match="inside the library"):
        series_relpath("../secret")
    with pytest.raises(ValueError, match="inside the library"):
        series_library_path(tmp_path, "/etc/passwd")
    assert (
        series_library_path(tmp_path, "Show [tvdbid=1]") == (tmp_path / "Show [tvdbid=1]").resolve()
    )


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


def test_index_series_mkvs_walks_season_and_specials(tmp_path: Path) -> None:
    from yt_dlp_emby.library import index_series_mkvs

    series = tmp_path / "Game Changer [tvdbid=361151]"
    season = series / "Season 1"
    specials = series / "Specials"
    season.mkdir(parents=True)
    specials.mkdir()
    ep = season / "Game Changer - S01E04 - Slug Eater.mkv"
    special = specials / "Game Changer - S00E12 - Cut for Time.mkv"
    ep.write_bytes(b"x")
    special.write_bytes(b"x")
    indexed = index_series_mkvs(series)
    assert indexed[(1, 4)] == ep
    assert indexed[(0, 12)] == special


def test_load_index_quarantines_corrupt_json(tmp_path: Path) -> None:
    from yt_dlp_emby.config import ConfigError

    series = tmp_path / "Example Channel"
    series.mkdir()
    index_path = series / ".yt-emby.json"
    index_path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="corrupt"):
        load_index(series)
    backups = list(series.glob(".yt-emby.json.corrupt-*"))
    assert backups
    assert backups[0].read_text(encoding="utf-8") == "{not json"
