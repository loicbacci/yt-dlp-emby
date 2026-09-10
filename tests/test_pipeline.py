from pathlib import Path

import pytest

from yt_dlp_emby.cache import CACHE_FILENAME, load_cache
from yt_dlp_emby.config import resolve_settings
from yt_dlp_emby.extract import ChannelArt, EpisodeInfo, PlaylistInfo
from yt_dlp_emby.pipeline import run_download
from yt_dlp_emby.style import strip_ansi


def _playlist() -> PlaylistInfo:
    return PlaylistInfo(
        playlist_id="PLa",
        title="Course",
        description="Playlist plot",
        channel="Example Channel",
        channel_id="UC1",
        thumbnail_url=None,
        episodes=[
            EpisodeInfo(
                video_id="vid1",
                title="Intro",
                description="",
                playlist_index=1,
                webpage_url="https://www.youtube.com/watch?v=vid1",
            )
        ],
    )


def _settings(
    tmp_path: Path,
    *,
    force_refetch: bool = False,
    dry_run: bool = False,
    quiet: bool = True,
    verbose: bool = False,
    debug: bool = False,
):
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n")
    ffmpeg.chmod(0o755)
    return resolve_settings(
        library=str(tmp_path / "lib"),
        old_dir=str(tmp_path / "old"),
        ffmpeg_location=str(ffmpeg),
        force_refetch=force_refetch,
        dry_run=dry_run,
        quiet=quiet,
        verbose=verbose,
        debug=debug,
        environ={},
        cwd=tmp_path,
    )


def _patch_extractors(monkeypatch: pytest.MonkeyPatch, calls: list[str]) -> None:
    def fake_extract_playlist(*_args: object, **_kwargs: object) -> PlaylistInfo:
        calls.append("list")
        return _playlist()

    def fake_extract_video(*_args: object, **_kwargs: object) -> EpisodeInfo:
        calls.append("extract_video")
        listing = _playlist().episodes[0]
        return EpisodeInfo(
            video_id=listing.video_id,
            title=listing.title,
            description="Fetched plot",
            playlist_index=listing.playlist_index,
            upload_date="20240101",
            duration=12,
            thumbnail_url="https://img.example/e.jpg",
            webpage_url=listing.webpage_url,
        )

    def fake_channel_art(*_args: object, **_kwargs: object) -> ChannelArt:
        calls.append("art")
        return ChannelArt("UC1", "Example Channel", "About", None, None)

    def fake_download(url: str, dest_stem: Path, _settings: object, format_selector: str | None = None) -> dict:
        calls.append("download")
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        dest_stem.with_suffix(".mkv").write_bytes(b"video")
        return {
            "id": "vid1",
            "title": "Intro",
            "description": "Full plot",
            "upload_date": "20240101",
            "duration": 12,
            "thumbnail": "https://img.example/e.jpg",
            "webpage_url": url,
        }

    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_playlist", fake_extract_playlist)
    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_video", fake_extract_video)
    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_channel_art", fake_channel_art)
    monkeypatch.setattr("yt_dlp_emby.pipeline.download_video", fake_download)
    monkeypatch.setattr("yt_dlp_emby.pipeline.download_image", lambda *_a, **_k: None)


def test_pipeline_starts_download_after_listing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    code = run_download("https://example.invalid/playlist", _settings(tmp_path))
    assert code == 0
    assert calls == ["list", "art", "download"]
    series = tmp_path / "lib" / "Example Channel"
    cache = load_cache(series)
    assert cache["vid1"]["description"] == "Full plot"
    assert (series / CACHE_FILENAME).is_file()
    nfo = next(p for p in (series / "Season 1").glob("*.nfo") if p.name != "season.nfo")
    assert "Full plot" in nfo.read_text(encoding="utf-8")


def test_pipeline_refresh_uses_cache_without_extract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    settings = _settings(tmp_path)
    assert run_download("https://example.invalid/playlist", settings) == 0
    calls.clear()
    assert run_download("https://example.invalid/playlist", settings) == 0
    assert calls == ["list", "art"]
    assert "extract_video" not in calls
    assert "download" not in calls


def test_pipeline_force_refetch_extracts_existing_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    calls.clear()
    assert (
        run_download(
            "https://example.invalid/playlist",
            _settings(tmp_path, force_refetch=True),
        )
        == 0
    )
    assert calls == ["list", "art", "extract_video"]
    cache = load_cache(tmp_path / "lib" / "Example Channel")
    assert cache["vid1"]["description"] == "Fetched plot"


def test_pipeline_skips_download_when_mkv_exists(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.library import episode_stem, load_index

    series = tmp_path / "lib" / "Example Channel"
    season = series / "Season 1"
    season.mkdir(parents=True)
    stem = episode_stem("Example Channel", 1, 1, "Intro")
    (season / f"{stem}.mkv").write_bytes(b"already")
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    assert "download" not in calls
    index = load_index(series)
    assert "vid1" in index.playlists["PLa"].episodes
    assert (season / f"{stem}.mkv").read_bytes() == b"already"


def test_pipeline_redownloads_when_existing_is_below_1080(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.library import episode_stem

    series = tmp_path / "lib" / "Example Channel"
    season = series / "Season 1"
    season.mkdir(parents=True)
    stem = episode_stem("Example Channel", 1, 1, "Intro")
    (season / f"{stem}.mkv").write_bytes(b"lowres")
    monkeypatch.setattr("yt_dlp_emby.pipeline.video_height", lambda *_a, **_k: 360)
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    assert "download" in calls


def test_pipeline_redownloads_refresh_when_below_1080(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    calls.clear()
    monkeypatch.setattr("yt_dlp_emby.pipeline.video_height", lambda *_a, **_k: 360)
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    assert "download" in calls


def test_pipeline_redownloads_when_mkv_missing_after_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from yt_dlp_emby.library import episode_stem

    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    stem = episode_stem("Example Channel", 1, 1, "Intro")
    mkv = tmp_path / "lib" / "Example Channel" / "Season 1" / f"{stem}.mkv"
    assert mkv.is_file()
    mkv.unlink()
    calls.clear()
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    assert "download" in calls


def test_pipeline_skips_unavailable_video_and_continues(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    playlist = PlaylistInfo(
        playlist_id="PLa",
        title="Course",
        description="Playlist plot",
        channel="Example Channel",
        channel_id="UC1",
        thumbnail_url=None,
        episodes=[
            EpisodeInfo(
                video_id="live1",
                title="Upcoming",
                description="",
                playlist_index=1,
                webpage_url="https://www.youtube.com/watch?v=live1",
            ),
            EpisodeInfo(
                video_id="vid2",
                title="Ready",
                description="",
                playlist_index=2,
                webpage_url="https://www.youtube.com/watch?v=vid2",
            ),
        ],
    )

    def fake_download(
        url: str, dest_stem: Path, _settings: object, format_selector: str | None = None
    ) -> dict:
        if "live1" in url:
            raise RuntimeError("no downloadable media (upcoming live/premiere)")
        dest_stem.parent.mkdir(parents=True, exist_ok=True)
        dest_stem.with_suffix(".mkv").write_bytes(b"video")
        return {
            "id": "vid2",
            "title": "Ready",
            "description": "Full plot",
            "upload_date": "20240101",
            "duration": 12,
            "webpage_url": url,
        }

    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_playlist", lambda *_a, **_k: playlist)
    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_channel_art", lambda *_a, **_k: None)
    monkeypatch.setattr("yt_dlp_emby.pipeline.download_video", fake_download)
    monkeypatch.setattr("yt_dlp_emby.pipeline.download_image", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "yt_dlp_emby.pipeline.extract_video",
        lambda url, index, **_k: playlist.episodes[index - 1],
    )
    code = run_download("https://example.invalid/playlist", _settings(tmp_path))
    assert code == 1
    season = tmp_path / "lib" / "Example Channel" / "Season 1"
    mkvs = list(season.glob("*.mkv"))
    assert len(mkvs) == 1
    assert "Ready" in mkvs[0].name


def test_pipeline_series_folder_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    code = run_download(
        "https://example.invalid/playlist",
        _settings(tmp_path),
        series_folder="Custom Series",
    )
    assert code == 0
    assert (tmp_path / "lib" / "Custom Series" / "Season 1").is_dir()
    assert not (tmp_path / "lib" / "Example Channel").exists()


def _playlist_named(playlist_id: str, video_id: str, title: str) -> PlaylistInfo:
    return PlaylistInfo(
        playlist_id=playlist_id,
        title="Course",
        description="Playlist plot",
        channel="Example Channel",
        channel_id="UC1",
        thumbnail_url=None,
        episodes=[
            EpisodeInfo(
                video_id=video_id,
                title=title,
                description="",
                playlist_index=1,
                webpage_url=f"https://www.youtube.com/watch?v={video_id}",
            )
        ],
    )


def test_pipeline_dry_run_prints_unit_plan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    code = run_download(
        "https://example.invalid/playlist",
        _settings(tmp_path, dry_run=True, quiet=False),
    )
    assert code == 0
    assert calls == ["list"]
    out = strip_ansi(capsys.readouterr().out)
    assert "Example Channel" in out
    assert "season 1 → Season 1" in out
    assert "1 download" in out
    assert "listed" in out
    assert "    download" in out
    assert "S01E01" in out
    assert out.count("Done") == 1
    assert "Listing playlist" not in out


def test_pipeline_dry_run_hides_skip_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    calls.clear()
    capsys.readouterr()
    assert (
        run_download(
            "https://example.invalid/playlist",
            _settings(tmp_path, dry_run=True, quiet=False),
        )
        == 0
    )
    assert calls == ["list"]
    out = strip_ansi(capsys.readouterr().out)
    assert "1 skip" in out
    assert "0 download" in out
    assert "    skip" not in out
    assert "    download" not in out


def test_pipeline_verbose_dry_run_prints_skip_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    assert run_download("https://example.invalid/playlist", _settings(tmp_path)) == 0
    capsys.readouterr()
    assert (
        run_download(
            "https://example.invalid/playlist",
            _settings(tmp_path, dry_run=True, quiet=False, verbose=True),
        )
        == 0
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "    skip" in out


def test_pipeline_debug_splits_listing_and_disk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[str] = []
    _patch_extractors(monkeypatch, calls)
    run_download(
        "https://example.invalid/playlist",
        _settings(tmp_path, dry_run=True, quiet=False, debug=True),
    )
    out = strip_ansi(capsys.readouterr().out)
    assert "listed" in out
    assert "disk" in out


def test_youtube_manifest_one_done(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from yt_dlp_emby.pipeline import run_youtube_manifest
    from yt_dlp_emby.youtube_manifest import YoutubeManifest, YoutubePlaylist, YoutubeSeries

    urls: list[str] = []

    def fake_extract_playlist(url: str, **_kwargs: object) -> PlaylistInfo:
        urls.append(url)
        if "PLaaaa" in url:
            return _playlist_named("PLa", "vid1", "Intro")
        return _playlist_named("PLb", "vid2", "Next")

    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_playlist", fake_extract_playlist)
    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_channel_art", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "yt_dlp_emby.pipeline.download_video",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("dry-run downloaded")),
    )
    monkeypatch.setattr("yt_dlp_emby.pipeline.download_image", lambda *_a, **_k: None)
    manifest = YoutubeManifest(
        library=tmp_path / "lib",
        old_dir=tmp_path / "old",
        series=(
            YoutubeSeries(
                name="Example Channel",
                playlists=(
                    YoutubePlaylist("https://www.youtube.com/playlist?list=PLaaaa", 1),
                    YoutubePlaylist("https://www.youtube.com/playlist?list=PLbbbb", 2),
                ),
            ),
        ),
    )
    assert run_youtube_manifest(manifest, _settings(tmp_path, dry_run=True, quiet=False)) == 0
    assert urls == [
        "https://www.youtube.com/playlist?list=PLaaaa",
        "https://www.youtube.com/playlist?list=PLbbbb",
    ]
    out = strip_ansi(capsys.readouterr().out)
    assert out.count("Example Channel") == 1
    assert "season 1 → Season 1" in out
    assert "season 2 → Season 2" in out
    assert out.count("Done") == 1
    assert "listed" in out

