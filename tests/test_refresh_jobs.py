from __future__ import annotations

import time

from yt_dlp_emby.server.refresh_jobs import RefreshJobStore


def test_refresh_job_status_survives_store_recreation_and_marks_interrupted(tmp_path) -> None:
    store = RefreshJobStore(tmp_path, ttl_seconds=3600, max_entries=10)
    items = [{"platform": "dropout", "slug": "show"}]
    created = store.create("job-1", items)
    store.update("job-1", progress={"completed": 1, "total": 3, "current": None})
    assert store.active()[0]["items"] == items

    restarted = RefreshJobStore(tmp_path, ttl_seconds=3600, max_entries=10)
    restarted.recover_interrupted()
    recovered = restarted.get("job-1")

    assert created["status"] == "running"
    assert recovered is not None
    assert recovered["status"] == "error"
    assert recovered["result"] is None
    assert "server restarted" in recovered["error"]
    assert recovered["progress"] == {"completed": 1, "total": 3, "current": None}
    assert restarted.active() == []


def test_refresh_job_store_prunes_expired_and_excess_jobs(tmp_path) -> None:
    store = RefreshJobStore(tmp_path, ttl_seconds=3600, max_entries=2)
    store.create("job-1", [])
    store.update("job-1", status="done")
    time.sleep(0.002)
    store.create("job-2", [])
    store.update("job-2", status="done")
    time.sleep(0.002)
    store.create("job-3", [])
    store.update("job-3", status="done")

    assert store.get("job-1") is None
    assert store.get("job-2") is not None
    assert store.get("job-3") is not None
