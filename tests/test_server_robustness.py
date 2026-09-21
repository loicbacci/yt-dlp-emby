"""Targeted tests for the server-robustness remediation (locks, errors, limits)."""

from __future__ import annotations

import json
import stat

import pytest

pytest.importorskip("fastapi")

from yt_dlp_emby.cache import dropout_cache_path, load_dropout_season_cache
from yt_dlp_emby.config import ConfigError

pytestmark = pytest.mark.web


def test_corrupt_dropout_cache_quarantines_and_raises(tmp_path) -> None:
    path = dropout_cache_path(tmp_path / "dropout.yaml")
    path.parent.mkdir(parents=True)
    path.write_text("{not json", encoding="utf-8")
    with pytest.raises(ConfigError, match="corrupt"):
        load_dropout_season_cache(path)
    assert list(path.parent.glob("dropout.json.corrupt-*"))


def test_validation_envelope_has_fields(authed_client) -> None:
    response = authed_client.put("/api/manifests/youtube", json={"nope": True})
    assert response.status_code == 400
    body = response.json()
    assert body["error"] == "validation error"
    assert isinstance(body["fields"], dict) and body["fields"]


def test_plans_routes_alias_runs_plan(authed_client, tmp_path) -> None:
    plan = {"generated_at": "2026-01-01T00:00:00+00:00", "force": False, "sources": {}}
    (tmp_path / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    latest = authed_client.get("/api/plans/latest")
    assert latest.status_code == 200
    assert latest.json()["generated_at"] == plan["generated_at"]
    legacy = authed_client.get("/api/runs/plan")
    assert legacy.status_code == 200
    assert legacy.json() == latest.json()


def test_delete_source_rejected_during_run(authed_client, tmp_path) -> None:
    (tmp_path / "dropout.yaml").write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\nseries: []\n",
        encoding="utf-8",
    )
    created = authed_client.post(
        "/api/series", json={"name": "Show", "platform": "dropout", "path": "Show"}
    )
    assert created.status_code == 200
    authed_client.app.state.runner._state.status = "running"
    try:
        response = authed_client.delete("/api/series/dropout/show/sources/0")
        assert response.status_code == 409
        assert response.json()["error"] == "a run is in progress"
    finally:
        authed_client.app.state.runner._state.status = "idle"


def test_delete_source_returns_updated_detail(authed_client, tmp_path) -> None:
    (tmp_path / "dropout.yaml").write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\nseries: []\n",
        encoding="utf-8",
    )
    created = authed_client.post(
        "/api/series", json={"name": "Show", "platform": "dropout", "path": "Show"}
    )
    assert created.status_code == 200
    # No sources to delete, but the point is the route shape: 404 for a bad
    # index, and 200 + SeriesDetail body (not 204-empty) on success. Seed one
    # source via a direct PUT so DELETE has something to remove.
    detail = created.json()
    detail["sources"] = [{"url": "https://watch.dropout.tv/show", "seasons": []}]
    saved = authed_client.put("/api/series/dropout/show", json=detail)
    assert saved.status_code == 200
    assert len(saved.json()["sources"]) == 1
    deleted = authed_client.delete("/api/series/dropout/show/sources/0")
    assert deleted.status_code == 200
    assert deleted.json()["sources"] == []


def test_download_ids_reject_bad_pattern(authed_client, tmp_path) -> None:
    (tmp_path / "youtube.yaml").write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: Example Channel\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLaaaa\n",
        encoding="utf-8",
    )
    (tmp_path / "plan.json").write_text(
        json.dumps({"generated_at": None, "force": False, "sources": {}}),
        encoding="utf-8",
    )
    response = authed_client.post("/api/runs", json={"ids": ["nope"]})
    assert response.status_code == 400
    assert response.json()["error"] == "validation error"


def test_only_file_written_private(tmp_path) -> None:
    import asyncio

    from yt_dlp_emby.server.runner import RunManager

    (tmp_path / "youtube.yaml").write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: Example Channel\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLaaaa\n",
        encoding="utf-8",
    )
    (tmp_path / "plan.json").write_text(
        json.dumps(
            {
                "generated_at": "2026-01-01T00:00:00+00:00",
                "force": False,
                "sources": {
                    "youtube": {
                        "ok": True,
                        "error": None,
                        "seasons": [],
                        "items": [
                            {
                                "id": "youtube|example-channel|S01E01",
                                "action": "download",
                                "code": "S01E01",
                                "title": "One",
                                "platform": "youtube",
                            }
                        ],
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    async def run() -> None:
        import sys

        runner = RunManager(
            tmp_path, command_factory=lambda *a, **k: [sys.executable, "-c", "pass"]
        )
        # File-stem slug with a space: the old SxxExx-only regex rejected this.
        await runner.start_download(["youtube|my show|S01E01"])
        await runner.stop()

    asyncio.run(run())
    only = tmp_path / "download-only.json"
    assert only.is_file()
    assert stat.S_IMODE(only.stat().st_mode) == 0o600


def test_sse_after_clamped(authed_client) -> None:
    assert authed_client.get("/api/runs/log", params={"after": -1}).status_code == 400
    assert authed_client.get("/api/runs/log", params={"after": 10001}).status_code == 400
    assert authed_client.get("/api/runs/events", params={"after": -5}).status_code == 400


def test_manifest_write_keeps_single_bak(authed_client, tmp_path) -> None:
    text = (
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\n"
        "series:\n  - name: Example Channel\n    playlists:\n"
        "      - url: https://www.youtube.com/playlist?list=PLaaaa\n"
    )
    first = authed_client.put("/api/manifests/youtube", json={"text": text})
    assert first.status_code == 200
    second = authed_client.put("/api/manifests/youtube", json={"text": text + "# v2\n"})
    assert second.status_code == 200
    baks = list(tmp_path.glob("youtube.yaml.bak"))
    assert len(baks) == 1
    assert "# v2" not in baks[0].read_text(encoding="utf-8")
