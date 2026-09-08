from pathlib import Path

import pytest

from yt_emby.config import Settings
from yt_emby.download import promote_episode


def test_promote_episode_copies_finished_files_not_partials(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    dest_dir = tmp_path / "library" / "Season 01"
    staging.mkdir()
    dest_dir.mkdir(parents=True)
    stem = "Show - S01E01 - Title"
    (staging / f"{stem}.mkv").write_bytes(b"video")
    (staging / f"{stem}.en.srt").write_text("subs")
    (staging / f"{stem}.mkv.part").write_bytes(b"partial")
    (staging / f"{stem}.ytdl").write_text("meta")

    promote_episode(staging / stem, dest_dir / stem)

    assert (dest_dir / f"{stem}.mkv").read_bytes() == b"video"
    assert (dest_dir / f"{stem}.en.srt").read_text() == "subs"
    assert not (dest_dir / f"{stem}.mkv.part").exists()
    assert not (dest_dir / f"{stem}.ytdl").exists()


def test_promote_episode_succeeds_when_copystat_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_copystat(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("yt_emby.download.shutil.copystat", deny_copystat)
    staging = tmp_path / "staging"
    dest_dir = tmp_path / "library" / "Season 01"
    staging.mkdir()
    dest_dir.mkdir(parents=True)
    stem = "Show - S01E01 - Title"
    (staging / f"{stem}.mkv").write_bytes(b"video")

    promote_episode(staging / stem, dest_dir / stem)

    assert (dest_dir / f"{stem}.mkv").read_bytes() == b"video"


def test_download_video_returns_extract_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_emby.download import download_video

    class FakeYDL:
        opts_seen: dict = {}

        def __init__(self, opts: dict) -> None:
            type(self).opts_seen = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            assert download is True
            return {"id": "vid1", "title": "Intro", "description": "Plot"}

    monkeypatch.setattr("yt_emby.download.YoutubeDL", FakeYDL)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    info = download_video("https://www.youtube.com/watch?v=vid1", tmp_path / "ep", settings)
    assert info["id"] == "vid1"
    assert info["description"] == "Plot"
    assert FakeYDL.opts_seen["writesubtitles"] is True
    assert FakeYDL.opts_seen["writeautomaticsub"] is False
    assert FakeYDL.opts_seen["subtitleslangs"] == ["en"]
    assert "extractor_args" not in FakeYDL.opts_seen
    assert "cookiefile" not in FakeYDL.opts_seen


def test_download_video_passes_cookiefile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_emby.download import download_video

    class FakeYDL:
        opts_seen: dict = {}

        def __init__(self, opts: dict) -> None:
            type(self).opts_seen = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            return {"id": "vid1"}

    monkeypatch.setattr("yt_emby.download.YoutubeDL", FakeYDL)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n")
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
        cookiefile=cookies,
    )
    download_video("https://www.youtube.com/watch?v=vid1", tmp_path / "ep", settings)
    assert FakeYDL.opts_seen["cookiefile"] == str(cookies)


def test_download_video_enables_node_js_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_emby.download import download_video

    class FakeYDL:
        opts_seen: dict = {}

        def __init__(self, opts: dict) -> None:
            type(self).opts_seen = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            return {"id": "vid1"}

    monkeypatch.setattr("yt_emby.download.YoutubeDL", FakeYDL)
    monkeypatch.setattr("yt_emby.extract.find_node", lambda: "/usr/bin/node")
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    download_video("https://www.youtube.com/watch?v=vid1", tmp_path / "ep", settings)
    assert FakeYDL.opts_seen["js_runtimes"] == {"node": {"path": "/usr/bin/node"}}


def test_download_video_empty_info_is_not_auth_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_emby.download import YoutubeAuthError, download_video

    class FakeYDL:
        def __init__(self, opts: dict) -> None:
            pass

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> None:
            return None

    monkeypatch.setattr("yt_emby.download.YoutubeDL", FakeYDL)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    try:
        download_video("https://www.youtube.com/watch?v=vid1", tmp_path / "ep", settings)
    except YoutubeAuthError:
        raise AssertionError("empty extract_info must not be treated as a bot check")
    except RuntimeError as exc:
        assert "no downloadable media" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")
