from pathlib import Path

from yt_dlp_emby.extract import EpisodeInfo, PlaylistInfo
from yt_dlp_emby.library import EpisodeRecord, PlaylistRecord
from yt_dlp_emby.sync import ActionKind, plan_sync


def _playlist(*episodes: EpisodeInfo) -> PlaylistInfo:
    return PlaylistInfo(
        playlist_id="PLa",
        title="Course",
        description="Plot",
        channel="Example Channel",
        channel_id="UC1",
        thumbnail_url=None,
        episodes=list(episodes),
    )


def _ep(video_id: str, index: int, title: str = "T", duration: float = 60, filesize: int = 100) -> EpisodeInfo:
    return EpisodeInfo(
        video_id=video_id,
        title=title,
        description="",
        playlist_index=index,
        duration=duration,
        filesize=filesize,
        upload_date="20240101",
    )


def _record(*episodes: EpisodeRecord) -> PlaylistRecord:
    return PlaylistRecord(
        playlist_id="PLa",
        season=1,
        title="Course",
        episodes={ep.video_id: ep for ep in episodes},
    )


def _stored(video_id: str, episode: int, duration: float = 60, filesize: int = 100) -> EpisodeRecord:
    return EpisodeRecord(
        video_id=video_id,
        episode=episode,
        title="T",
        basename=f"Example Channel - S01E{episode:02d} - T",
        duration=duration,
        filesize=filesize,
        upload_date="20240101",
    )


def test_plan_adds_all_when_index_empty() -> None:
    plan = plan_sync(_playlist(_ep("a", 1), _ep("b", 2)), None, season=1)
    assert [a.kind for a in plan] == [ActionKind.ADD, ActionKind.ADD]
    assert [a.episode for a in plan] == [1, 2]


def test_plan_removes_missing_ids() -> None:
    plan = plan_sync(
        _playlist(_ep("a", 1)),
        _record(_stored("a", 1), _stored("gone", 2)),
        season=1,
    )
    kinds = {a.kind: a for a in plan}
    assert ActionKind.REMOVE in {a.kind for a in plan}
    assert kinds[ActionKind.REMOVE].video_id == "gone"


def test_plan_renames_on_reorder() -> None:
    plan = plan_sync(
        _playlist(_ep("b", 1, title="B"), _ep("a", 2, title="A")),
        _record(_stored("a", 1), _stored("b", 2)),
        season=1,
    )
    renames = [a for a in plan if a.kind == ActionKind.RENAME]
    assert len(renames) == 2
    assert {a.episode for a in renames} == {1, 2}


def test_plan_replace_on_duration_change() -> None:
    plan = plan_sync(
        _playlist(_ep("a", 1, duration=200)),
        _record(_stored("a", 1, duration=60)),
        season=1,
    )
    assert plan[0].kind == ActionKind.REPLACE
    assert plan[0].video_id == "a"


def test_plan_ignores_one_second_duration_jitter() -> None:
    plan = plan_sync(
        _playlist(_ep("a", 1, duration=61)),
        _record(_stored("a", 1, duration=60)),
        season=1,
    )
    assert plan[0].kind == ActionKind.REFRESH


def test_move_removed_files(tmp_path: Path) -> None:
    from yt_dlp_emby.sync import move_episode_files

    season = tmp_path / "series" / "Season 1"
    season.mkdir(parents=True)
    stem = "Example Channel - S01E01 - T"
    (season / f"{stem}.mkv").write_bytes(b"vid")
    (season / f"{stem}.nfo").write_text("nfo")
    (season / f"{stem}-thumb.jpg").write_bytes(b"jpg")
    (season / f"{stem}.en.srt").write_text("subs")
    dest = tmp_path / "old"
    moved = move_episode_files(season, stem, dest)
    assert not (season / f"{stem}.mkv").exists()
    assert (dest / f"{stem}.mkv").is_file()
    assert (dest / f"{stem}.en.srt").is_file()
    assert len(moved) == 4


def test_rename_episode_files(tmp_path: Path) -> None:
    from yt_dlp_emby.sync import rename_episode_files

    season = tmp_path / "Season 1"
    season.mkdir()
    old = "Example Channel - S01E02 - T"
    new = "Example Channel - S01E01 - T"
    (season / f"{old}.mkv").write_bytes(b"vid")
    (season / f"{old}.nfo").write_text("nfo")
    rename_episode_files(season, old, new)
    assert (season / f"{new}.mkv").is_file()
    assert (season / f"{new}.nfo").is_file()
    assert not (season / f"{old}.mkv").exists()
