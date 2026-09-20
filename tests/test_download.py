from pathlib import Path
from io import StringIO

import pytest

from yt_dlp_emby.config import Settings
from yt_dlp_emby.download import cleanup_stale_staging, mark_live_staging, promote_episode


def _touch_mkv(opts: dict) -> None:
    Path(str(opts["outtmpl"]).removesuffix(".%(ext)s") + ".mkv").write_bytes(b"mkv")


def test_promote_episode_copies_finished_files_not_partials(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    dest_dir = tmp_path / "library" / "Season 1"
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
    assert not (staging / f"{stem}.mkv").exists()
    assert not (staging / f"{stem}.en.srt").exists()
    assert not (staging / f"{stem}.mkv.part").exists()
    assert not (staging / f"{stem}.ytdl").exists()


def test_promote_episode_skips_stream_fragments_and_temp_mkv(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    dest_dir = tmp_path / "library" / "Season 13"
    staging.mkdir()
    dest_dir.mkdir(parents=True)
    stem = "Dimension 20 - S13E08 - Wallops at Swallop's"
    (staging / f"{stem}.mkv").write_bytes(b"final")
    (staging / f"{stem}.en.srt").write_text("subs")
    (staging / f"{stem}.temp.mkv").write_bytes(b"merge")
    (staging / f"{stem}.fhls-fastly_skyfire-4634.mp4").write_bytes(b"video")
    (staging / f"{stem}.fhls-fastly_skyfire-audio-high-Original.mp4").write_bytes(b"audio")
    promote_episode(staging / stem, dest_dir / stem)
    assert (dest_dir / f"{stem}.mkv").read_bytes() == b"final"
    assert (dest_dir / f"{stem}.en.srt").read_text() == "subs"
    assert not (dest_dir / f"{stem}.temp.mkv").exists()
    assert not list(dest_dir.glob("*.mp4"))
    assert not (staging / f"{stem}.mkv").exists()
    assert not (staging / f"{stem}.temp.mkv").exists()
    assert not (staging / f"{stem}.fhls-fastly_skyfire-4634.mp4").exists()


def test_promote_episode_does_not_delete_other_staged_files(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    dest_dir = tmp_path / "library" / "Season 1"
    staging.mkdir()
    dest_dir.mkdir(parents=True)
    stem = "Show - S01E01 - Title"
    other = "Show - S01E02 - Next"
    (staging / f"{stem}.mkv").write_bytes(b"one")
    (staging / f"{other}.mkv").write_bytes(b"two")
    promote_episode(staging / stem, dest_dir / stem)
    assert not (staging / f"{stem}.mkv").exists()
    assert (staging / f"{other}.mkv").read_bytes() == b"two"


def test_promote_episode_succeeds_when_copystat_is_denied(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def deny_copystat(*_args: object, **_kwargs: object) -> None:
        raise PermissionError(1, "Operation not permitted")

    monkeypatch.setattr("yt_dlp_emby.download.shutil.copystat", deny_copystat)
    staging = tmp_path / "staging"
    dest_dir = tmp_path / "library" / "Season 1"
    staging.mkdir()
    dest_dir.mkdir(parents=True)
    stem = "Show - S01E01 - Title"
    (staging / f"{stem}.mkv").write_bytes(b"video")

    promote_episode(staging / stem, dest_dir / stem)

    assert (dest_dir / f"{stem}.mkv").read_bytes() == b"video"
    assert not (staging / f"{stem}.mkv").exists()


def test_copy_with_progress_writes_chunks(tmp_path: Path) -> None:
    from yt_dlp_emby.progress import DownloadProgress, copy_with_progress

    src = tmp_path / "src.bin"
    dest = tmp_path / "dest.bin"
    src.write_bytes(b"x" * 32)
    stream = StringIO()
    progress = DownloadProgress(enabled=True, stream=stream, live=True)
    copy_with_progress(src, dest, progress, min_size=1)
    assert dest.read_bytes() == src.read_bytes()
    assert "copy" in stream.getvalue()


def test_download_video_returns_extract_info(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_dlp_emby.download import download_video

    class FakeYDL:
        opts_seen: dict = {}

        def __init__(self, opts: dict) -> None:
            type(self).opts_seen = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        processed = False

        def extract_info(self, url: str, download: bool = True) -> dict:
            assert download is False
            return {
                "id": "vid1",
                "title": "Intro",
                "description": "Plot",
                "vcodec": "avc1",
                "acodec": "mp4a",
            }

        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            assert download is True
            type(self).processed = True
            _touch_mkv(self.opts_seen)
            return info

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", FakeYDL)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    info = download_video("https://www.youtube.com/watch?v=vid1", tmp_path / "ep", settings)
    assert FakeYDL.processed is True
    assert info["id"] == "vid1"
    assert info["description"] == "Plot"
    assert FakeYDL.opts_seen["writesubtitles"] is True
    assert FakeYDL.opts_seen["writeautomaticsub"] is False
    assert FakeYDL.opts_seen["subtitleslangs"] == ["en"]
    assert FakeYDL.opts_seen["keepvideo"] is False
    assert FakeYDL.opts_seen["final_ext"] == "mkv"
    assert "extractor_args" not in FakeYDL.opts_seen
    assert "cookiefile" not in FakeYDL.opts_seen


def test_download_video_all_subtitle_langs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_dlp_emby.download import download_video

    class FakeYDL:
        opts_seen: dict = {}

        def __init__(self, opts: dict) -> None:
            type(self).opts_seen = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            info = {"id": "vid1", "vcodec": "avc1", "acodec": "mp4a"}
            if download:
                _touch_mkv(self.opts_seen)
            return info

        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            if download:
                _touch_mkv(self.opts_seen)
            return info

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", FakeYDL)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    download_video(
        "https://watch.dropout.tv/videos/ep",
        tmp_path / "ep",
        settings,
        subtitleslangs=["all"],
    )
    assert FakeYDL.opts_seen["subtitleslangs"] == ["all"]


def test_download_video_passes_cookiefile(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from yt_dlp_emby.download import download_video

    class FakeYDL:
        opts_seen: dict = {}

        def __init__(self, opts: dict) -> None:
            type(self).opts_seen = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            info = {"id": "vid1", "vcodec": "avc1", "acodec": "mp4a"}
            if download:
                _touch_mkv(self.opts_seen)
            return info

        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            if download:
                _touch_mkv(self.opts_seen)
            return info

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", FakeYDL)
    cookies = tmp_path / "cookies.txt"
    cookies.write_text("# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tNAME\tvalue\n")
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
        cookiefile=cookies,
    )
    download_video("https://www.youtube.com/watch?v=vid1", tmp_path / "ep", settings)
    used = FakeYDL.opts_seen["cookiefile"]
    assert used != str(cookies)
    assert Path(used).name.startswith("yt-dlp-emby-cookies-")
    assert cookies.is_file()


def test_download_video_does_not_let_ydl_empty_cookiefile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.download import download_video

    class WipingYDL:
        def __init__(self, opts: dict) -> None:
            self.opts = opts

        def __enter__(self) -> "WipingYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            Path(self.opts["cookiefile"]).write_text("")
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            info = {"id": "vid1", "vcodec": "avc1", "acodec": "mp4a"}
            if download:
                _touch_mkv(self.opts)
            return info

        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            if download:
                _touch_mkv(self.opts)
            return info

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", WipingYDL)
    cookies = tmp_path / "cookies.txt"
    original = "# Netscape HTTP Cookie File\n.youtube.com\tTRUE\t/\tTRUE\t0\tNAME\tvalue\n"
    cookies.write_text(original)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
        cookiefile=cookies,
    )
    download_video("https://www.youtube.com/watch?v=vid1", tmp_path / "ep", settings)
    assert cookies.read_text() == original


def test_download_video_enables_node_js_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.download import download_video

    class FakeYDL:
        opts_seen: dict = {}

        def __init__(self, opts: dict) -> None:
            type(self).opts_seen = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            info = {"id": "vid1", "vcodec": "avc1", "acodec": "mp4a"}
            if download:
                _touch_mkv(self.opts_seen)
            return info

        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            if download:
                _touch_mkv(self.opts_seen)
            return info

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", FakeYDL)
    monkeypatch.setattr("yt_dlp_emby.extract.find_node", lambda: "/usr/bin/node")
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    download_video("https://www.youtube.com/watch?v=vid1", tmp_path / "ep", settings)
    assert FakeYDL.opts_seen["js_runtimes"] == {"node": {"path": "/usr/bin/node"}}


@pytest.mark.parametrize(
    "stem",
    [
        "Dimension 20 - S01E17 - Prompocalypse Pt. 2",
        "Dimension 20 - S01E16 - Prompocalypse Pt. 1",
        "Dimension 20 - S03E17 - Times Squaremageddon Pt. 2",
        "Example Channel - S01E01 - Dr. Strange",
    ],
)
def test_download_video_accepts_titles_with_dots_in_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stem: str
) -> None:
    from yt_dlp_emby.download import download_video

    class FakeYDL:
        opts_seen: dict = {}

        def __init__(self, opts: dict) -> None:
            type(self).opts_seen = opts

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            info = {"id": "vid1", "vcodec": "avc1", "acodec": "mp4a"}
            if download:
                _touch_mkv(self.opts_seen)
            return info

        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            if download:
                _touch_mkv(self.opts_seen)
            return info

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", FakeYDL)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    dest = tmp_path / stem
    wrong = dest.with_suffix(".mkv")
    assert wrong.name != f"{dest.name}.mkv", "pathlib with_suffix must not be used for these stems"
    info = download_video("https://watch.dropout.tv/x/videos/example", dest, settings)
    assert info["id"] == "vid1"
    assert (tmp_path / f"{stem}.mkv").is_file()
    assert not wrong.is_file()


def test_download_video_pt_title_fails_when_only_wrong_with_suffix_mkv_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Regression: pathlib treats '. 2' as the suffix and looks for the wrong file."""
    from yt_dlp_emby.download import download_video

    class FakeYDL:
        def __init__(self, opts: dict) -> None:
            pass

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> dict:
            return {"id": "vid1", "vcodec": "avc1", "acodec": "mp4a"}

        def process_ie_result(self, info: dict, download: bool = True) -> dict:
            return info

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", FakeYDL)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    dest = tmp_path / "Dimension 20 - S01E17 - Prompocalypse Pt. 2"
    dest.with_suffix(".mkv").write_bytes(b"wrong path")
    with pytest.raises(RuntimeError, match="did not produce an mkv"):
        download_video("https://watch.dropout.tv/x/videos/example", dest, settings)


def test_promote_episode_copies_pt_dot_title(tmp_path: Path) -> None:
    staging = tmp_path / "staging"
    dest_dir = tmp_path / "library" / "Season 1"
    staging.mkdir()
    dest_dir.mkdir(parents=True)
    stem = "Dimension 20 - S01E17 - Prompocalypse Pt. 2"
    (staging / f"{stem}.mkv").write_bytes(b"video")
    (staging / f"{stem}.en.srt").write_text("subs")

    promote_episode(staging / stem, dest_dir / stem)

    assert (dest_dir / f"{stem}.mkv").read_bytes() == b"video"
    assert (dest_dir / f"{stem}.en.srt").read_text() == "subs"
    assert not (staging / f"{stem}.mkv").exists()


def test_download_video_empty_info_is_not_auth_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.download import YoutubeAuthError, download_video

    class FakeYDL:
        def __init__(self, opts: dict) -> None:
            pass

        def __enter__(self) -> "FakeYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> None:
            return None

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", FakeYDL)
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
        assert "did not produce an mkv" in str(exc) or "extract_info returned no metadata" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_download_video_auth_error_from_ydl_log(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.auth import DropoutAuthError
    from yt_dlp_emby.download import download_video

    class AuthFailYDL:
        def __init__(self, opts: dict) -> None:
            self.opts = opts

        def __enter__(self) -> "AuthFailYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> None:
            self.opts["logger"].error(
                "[Dropout] ep: This video is only available for registered users."
            )
            return None

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", AuthFailYDL)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    try:
        download_video("https://watch.dropout.tv/videos/ep", tmp_path / "ep", settings)
    except DropoutAuthError:
        return
    raise AssertionError("expected DropoutAuthError")


def test_download_video_reports_ydl_error_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.download import download_video

    class FragFailYDL:
        def __init__(self, opts: dict) -> None:
            self.opts = opts

        def __enter__(self) -> "FragFailYDL":
            return self

        def __exit__(self, *args: object) -> bool:
            return False

        def extract_info(self, url: str, download: bool = True) -> None:
            self.opts["logger"].error("Unable to rename file: [Errno 2] No such file or directory")
            return None

    monkeypatch.setattr("yt_dlp_emby.download.YoutubeDL", FragFailYDL)
    settings = Settings(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        ffmpeg=tmp_path / "ffmpeg",
        quiet=True,
    )
    try:
        download_video("https://watch.dropout.tv/videos/ep", tmp_path / "ep", settings)
    except RuntimeError as exc:
        assert "Unable to rename file" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_cleanup_stale_staging_removes_unresumable_leftovers(tmp_path: Path) -> None:
    temp_dir = tmp_path / "tmp"
    staging = tmp_path / "staging"
    temp_dir.mkdir()
    staging.mkdir()
    leftover = temp_dir / "yt-dlp-emby-abc123"
    leftover.mkdir()
    (leftover / "partial.temp.mkv").write_bytes(b"x")
    dropout_left = staging / "yt-dlp-emby-dropout-xyz"
    dropout_left.mkdir()
    cookies = temp_dir / "yt-dlp-emby-cookies-zzzz.txt"
    cookies.write_text("cookies")
    legacy = temp_dir / "yt-emby-oldrun"
    legacy.mkdir()
    keep_dir = temp_dir / "other-app"
    keep_dir.mkdir()
    keep_named = temp_dir / "yt-dlp-emby"
    keep_named.mkdir()
    keep_file = staging / "unrelated.txt"
    keep_file.write_text("keep")

    removed = cleanup_stale_staging(staging, temp_dir=temp_dir)

    assert removed == 4
    assert not leftover.exists()
    assert not dropout_left.exists()
    assert not cookies.exists()
    assert not legacy.exists()
    assert keep_dir.is_dir()
    assert keep_named.is_dir()
    assert keep_file.read_text() == "keep"


def test_cleanup_stale_staging_does_not_delete_staging_root(tmp_path: Path) -> None:
    staging = tmp_path / "yt-dlp-emby"
    staging.mkdir()
    (staging / "keep.txt").write_text("ok")
    leftover = staging / "yt-dlp-emby-oldrun"
    leftover.mkdir()
    unused_tmp = tmp_path / "empty-tmp"
    unused_tmp.mkdir()

    removed = cleanup_stale_staging(staging, temp_dir=unused_tmp)

    assert removed == 1
    assert staging.is_dir()
    assert (staging / "keep.txt").read_text() == "ok"
    assert not leftover.exists()


def test_cleanup_stale_staging_scans_same_root_once(tmp_path: Path) -> None:
    leftover = tmp_path / "yt-dlp-emby-run"
    leftover.mkdir()
    assert cleanup_stale_staging(tmp_path, temp_dir=tmp_path) == 1
    assert not leftover.exists()


def test_cleanup_stale_staging_skips_live_run_dir(tmp_path: Path) -> None:
    live = tmp_path / "yt-dlp-emby-dropout-live"
    live.mkdir()
    mark_live_staging(live)
    dead = tmp_path / "yt-dlp-emby-dropout-dead"
    dead.mkdir()
    (dead / ".yt-emby-pid").write_text("2000000000", encoding="utf-8")
    (dead / "partial.mkv").write_bytes(b"x")

    assert cleanup_stale_staging(temp_dir=tmp_path) == 1
    assert live.is_dir()
    assert (live / ".yt-dlp-emby-pid").is_file()
    assert not dead.exists()
