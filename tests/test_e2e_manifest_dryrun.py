"""Mocked YouTube/Dropout dry-runs produce a plan of .mkv destinations (no network)."""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

import pytest

from yt_dlp_emby.config import resolve_settings
from yt_dlp_emby.dropout import run_dropout
from yt_dlp_emby.dropout_manifest import load_dropout_manifest
from yt_dlp_emby.events import reset_runtime
from yt_dlp_emby.extract import DropoutListing, EpisodeInfo, PlaylistInfo
from yt_dlp_emby.library import episode_stem
from yt_dlp_emby.pipeline import run_youtube_manifest
from yt_dlp_emby.youtube_manifest import load_youtube_manifest

CODE_RE = re.compile(r"^S(\d+)E(\d+)$")


def _ffmpeg(tmp_path: Path) -> Path:
    ffmpeg = tmp_path / "ffmpeg"
    ffmpeg.write_text("#!/bin/sh\n", encoding="utf-8")
    ffmpeg.chmod(0o755)
    return ffmpeg


def _settings(tmp_path: Path):
    return resolve_settings(
        library=str(tmp_path / "lib"),
        old_dir=str(tmp_path / "old"),
        ffmpeg_location=str(_ffmpeg(tmp_path)),
        dry_run=True,
        quiet=True,
        environ={},
        cwd=tmp_path,
        use_default_config=False,
        auto_cookies=False,
    )


def _planned_mkv(
    library: Path, series: str, folder: str, dest_season: int, code: str, title: str
) -> Path:
    match = CODE_RE.fullmatch(code)
    assert match, code
    episode = int(match.group(2))
    stem = episode_stem(series, dest_season, episode, title)
    return library / series / folder / f"{stem}.mkv"


def _assert_download_plan_mkvs(plan: dict, platform: str, library: Path) -> None:
    items = plan["sources"][platform]["items"]
    downloads = [row for row in items if row.get("action") == "download"]
    assert downloads, f"expected download items in {platform} plan, got {items!r}"
    dests = [
        _planned_mkv(
            library,
            row["series"],
            row["folder"],
            int(row["dest_season"]),
            row["code"],
            row["title"],
        )
        for row in downloads
    ]
    assert all(path.suffix == ".mkv" for path in dests)
    assert not any(path.exists() for path in dests)
    assert not list(library.rglob("*.mkv"))


def test_youtube_dry_run_plan_mkv_dests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lib = tmp_path / "lib"
    manifest_path = tmp_path / "youtube.yaml"
    manifest_path.write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: Example Channel\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLaaaa\n        season: 1\n",
        encoding="utf-8",
    )

    def fake_extract_playlist(*_args: object, **_kwargs: object) -> PlaylistInfo:
        return PlaylistInfo(
            playlist_id="PLaaaa",
            title="Course",
            description="",
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

    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_playlist", fake_extract_playlist)
    monkeypatch.setattr(
        "yt_dlp_emby.pipeline.extract_channel_art",
        lambda *_a, **_k: None,
    )
    monkeypatch.setattr(
        "yt_dlp_emby.pipeline.extract_video",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no network")),
    )

    events = tmp_path / "events.jsonl"
    reset_runtime()
    monkeypatch.setenv("YT_DLP_EMBY_EVENTS", str(events))
    try:
        code = run_youtube_manifest(load_youtube_manifest(manifest_path), _settings(tmp_path))
    finally:
        os.environ.pop("YT_DLP_EMBY_EVENTS", None)
        reset_runtime()

    assert code == 0
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    _assert_download_plan_mkvs(plan, "youtube", lib)


def test_dropout_dry_run_plan_mkv_dests(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    lib = tmp_path / "lib"
    manifest_path = tmp_path / "dropout.yaml"
    manifest_path.write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: Game Changer\n    path: Game Changer\n"
        "    url: https://watch.dropout.tv/game-changer\n"
        "    seasons:\n      - dropout: 1\n",
        encoding="utf-8",
    )

    def fake_extract(_url: str, **_kwargs: object) -> list[DropoutListing]:
        return [
            DropoutListing(
                url="https://watch.dropout.tv/game-changer/videos/pilot",
                title="Pilot",
                dropout_episode=1,
            )
        ]

    monkeypatch.setattr("yt_dlp_emby.dropout.extract_dropout_season", fake_extract)
    monkeypatch.setattr(
        "yt_dlp_emby.extract.extract_dropout_season",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no network")),
    )

    events = tmp_path / "events.jsonl"
    reset_runtime()
    monkeypatch.setenv("YT_DLP_EMBY_EVENTS", str(events))
    try:
        code = run_dropout(
            load_dropout_manifest(manifest_path),
            _settings(tmp_path),
            create=True,
        )
    finally:
        os.environ.pop("YT_DLP_EMBY_EVENTS", None)
        reset_runtime()

    assert code == 0
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    _assert_download_plan_mkvs(plan, "dropout", lib)


@pytest.mark.web
async def test_cli_server_roundtrip_plan_events_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """CLI-written plan/events are read back by the server; ONLY ids honored.

    CLI -> server: mocked dry-run writes plan.json + events.jsonl, then
    GET /api/runs/plan and the runner event poller read them back.
    Server -> CLI: start_download() writes download-only.json, which the
    CLI-side YT_DLP_EMBY_ONLY gate (allowed_item_id) honors.
    """
    pytest.importorskip("fastapi")
    from fastapi.testclient import TestClient

    from yt_dlp_emby.events import allowed_item_id, read_events_path
    from yt_dlp_emby.server.app import create_app
    from yt_dlp_emby.server.runner import RunManager

    lib = tmp_path / "lib"
    manifest_path = tmp_path / "youtube.yaml"
    manifest_path.write_text(
        f"library: {lib}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: Example Channel\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLaaaa\n        season: 1\n",
        encoding="utf-8",
    )

    def fake_extract_playlist(*_args: object, **_kwargs: object) -> PlaylistInfo:
        return PlaylistInfo(
            playlist_id="PLaaaa",
            title="Course",
            description="",
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
                ),
                EpisodeInfo(
                    video_id="vid2",
                    title="Outro",
                    description="",
                    playlist_index=2,
                    webpage_url="https://www.youtube.com/watch?v=vid2",
                ),
            ],
        )

    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_playlist", fake_extract_playlist)
    monkeypatch.setattr("yt_dlp_emby.pipeline.extract_channel_art", lambda *_a, **_k: None)
    monkeypatch.setattr(
        "yt_dlp_emby.pipeline.extract_video",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("no network")),
    )

    events_path = tmp_path / "events.jsonl"
    reset_runtime()
    monkeypatch.setenv("YT_DLP_EMBY_EVENTS", str(events_path))
    try:
        code = run_youtube_manifest(load_youtube_manifest(manifest_path), _settings(tmp_path))
    finally:
        os.environ.pop("YT_DLP_EMBY_EVENTS", None)
        reset_runtime()
    assert code == 0

    # CLI -> server: plan.json read back with .mkv dests.
    plan = json.loads((tmp_path / "plan.json").read_text(encoding="utf-8"))
    _assert_download_plan_mkvs(plan, "youtube", lib)
    downloads = [
        row for row in plan["sources"]["youtube"]["items"] if row.get("action") == "download"
    ]
    assert len(downloads) == 2
    with TestClient(create_app(data_dir=tmp_path, environ={})) as client:
        client.post("/api/setup", json={"password": "secretpass"})
        served = client.get("/api/runs/plan").json()
        assert [row["id"] for row in served["sources"]["youtube"]["items"]] == [
            row["id"] for row in plan["sources"]["youtube"]["items"]
        ]
        assert client.get("/api/runs").json()["plan"]["pending"] == 2

    # CLI -> server: events.jsonl picked up by the runner poller.
    assert events_path.is_file()
    reader = RunManager(tmp_path)
    reader._poll_events_file()
    kinds = [item.event.get("event") for item in reader.events_after(0)]
    assert "run_finished" in kinds
    assert "series" in kinds

    # Server -> CLI: start_download writes download-only.json; gate honors it.
    chosen = downloads[0]["id"]
    other = downloads[1]["id"]
    writer = RunManager(
        tmp_path,
        command_factory=lambda *a, **k: [sys.executable, "-c", "pass"],
    )
    await writer.start_download([chosen])
    await writer.stop()
    only = json.loads((tmp_path / "download-only.json").read_text(encoding="utf-8"))
    assert only["ids"] == [chosen]
    try:
        read_events_path({"YT_DLP_EMBY_ONLY": str(tmp_path / "download-only.json")})
        assert allowed_item_id(chosen) is True
        assert allowed_item_id(other) is False
    finally:
        reset_runtime()
