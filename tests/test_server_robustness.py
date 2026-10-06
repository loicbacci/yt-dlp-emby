"""Targeted tests for the server-robustness remediation (locks, errors, limits)."""

from __future__ import annotations

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


def test_queue_is_cached_and_empty_without_filesystem_scan(authed_client, tmp_path) -> None:
    response = authed_client.get("/api/queue")
    assert response.status_code == 200
    assert response.json()["readiness"] == "loading"
    assert not (tmp_path / "lib").exists()


def test_canonical_edit_rejected_during_job(authed_client, tmp_path) -> None:
    (tmp_path / "dropout.yaml").write_text(
        f"library: {tmp_path / 'lib'}\nold_dir: {tmp_path / 'old'}\nseries: []\n",
        encoding="utf-8",
    )
    created = authed_client.post(
        "/api/series", json={"name": "Show", "platform": "dropout", "path": "Show"}
    )
    assert created.status_code == 200
    authed_client.app.state.job_store.create(
        "busy", "diagnostics", {"kind": "diagnostics", "checks": ["database"]}
    )
    response = authed_client.put("/api/series/dropout/show", json=created.json())
    assert response.status_code == 409
    assert response.json()["code"] == "JOB_CONFLICT"


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
