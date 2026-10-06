"""Unified durable job API contract tests."""

from __future__ import annotations

import sys
import textwrap
import time

import pytest

pytest.importorskip("fastapi")

from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app, resolve_data_dir

pytestmark = pytest.mark.web


def _worker(script: str):
    return lambda _request: [sys.executable, "-c", script]


def _client(path, worker=None):
    client = TestClient(create_app(data_dir=path, environ={}, worker_command_factory=worker))
    client.__enter__()
    assert client.post("/api/setup", json={"password": "secretpass"}).status_code == 200
    return client


def test_health_and_auth_protection(client) -> None:
    assert client.get("/api/health").json() == {"ok": True}
    response = client.get("/api/jobs")
    assert response.status_code == 401
    assert response.json()["error"] == "unauthorized"


def test_job_contract_completes_and_lists(tmp_path) -> None:
    script = textwrap.dedent(
        """
        import json,sys
        sys.stdin.readline()
        print(json.dumps({'v':1,'seq':1,'type':'progress','stage':'diagnostics','completed':0,'total':1}), flush=True)
        print(json.dumps({'v':1,'seq':2,'type':'result','result':{'ok':True}}), flush=True)
        """
    )
    client = _client(tmp_path, _worker(script))
    try:
        response = client.post("/api/jobs", json={"kind": "diagnostics", "checks": ["database"]})
        assert response.status_code == 202
        start = response.json()
        assert start["status"] == "queued" and start["job_id"]
        for _ in range(100):
            snapshot = client.get(f"/api/jobs/{start['job_id']}").json()
            if snapshot["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.01)
        assert snapshot["status"] == "succeeded", snapshot
        assert snapshot["progress"] == {"stage": "diagnostics", "completed": 0, "total": 1}
        assert snapshot["result"] == {"ok": True}
        assert snapshot["can_retry"] is False and snapshot["can_cancel"] is False
        listed = client.get("/api/jobs").json()
        assert listed["active"] is None
        assert listed["total"] == 1
        assert listed["history"][0]["id"] == start["job_id"]
    finally:
        client.__exit__(None, None, None)


def test_job_validation_and_error_envelope(authed_client) -> None:
    bad = authed_client.post("/api/jobs", json={"kind": "diagnostics", "checks": ["made-up"]})
    assert bad.status_code == 400
    assert bad.json()["code"] == "INVALID_REQUEST"
    assert bad.json()["request_id"]
    missing = authed_client.get("/api/jobs/missing")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    assert missing.json()["request_id"]


def test_retry_skips_only_disk_verified_download_completions(authed_client, monkeypatch) -> None:
    from yt_dlp_emby.server import app as app_module
    from yt_dlp_emby.server import services

    store = authed_client.app.state.job_store
    job_id = "retry-parent"
    completed = {
        "id": "act-done",
        "execution_id": "youtube|show|S01E01",
        "platform": "youtube",
        "slug": "show",
        "provider_identity": "video-done",
        "action": "download",
    }
    unverified = {
        "id": "act-pending",
        "execution_id": "youtube|show|S01E02",
        "platform": "youtube",
        "slug": "show",
        "provider_identity": "video-pending",
        "action": "download",
    }
    cached_view = {
        "platform": "youtube",
        "slug": "show",
        "view": {"target": {"platform": "youtube", "slug": "show"}},
    }
    store.create(
        job_id,
        "download",
        {
            "kind": "download",
            "plan_id": "old-plan",
            "ids": ["act-done", "act-pending"],
            "selected_actions": [completed, unverified],
            "cached_views": [cached_view],
            "force": False,
            "create": False,
        },
    )
    store.update(job_id, status="failed")
    store.item(job_id, "done", {"id": "act-done"}, "succeeded", {"ok": True})
    store.item(job_id, "pending", {"id": "act-pending"}, "succeeded", {"ok": True})

    monkeypatch.setattr(services, "verify_completed_actions", lambda *args: {"act-done"})
    refreshed = {
        "platform": "youtube",
        "slug": "show",
        "view": {"target": {"platform": "youtube", "slug": "show"}},
        "plan": {"plan_id": "target-plan", "revision": "rev"},
    }
    monkeypatch.setattr(services, "refresh_cached_disk_views", lambda *args, **kwargs: [refreshed])
    monkeypatch.setattr(
        app_module.cached_views,
        "latest_plan",
        lambda *args, **kwargs: {
            "plan_id": "new-plan",
            "sources": {
                "youtube": {
                    "items": [
                        {**completed, "id": "act-done-present", "action": "present"},
                        {**unverified, "id": "act-pending-replanned", "action": "download"},
                    ]
                }
            },
        },
    )
    selected = {
        "selected_actions": [{**unverified, "id": "act-pending-replanned"}],
        "cached_views": [cached_view],
    }
    monkeypatch.setattr(
        app_module.cached_views, "executable_selection", lambda *args, **kwargs: selected
    )
    coordinator = authed_client.app.state.job_coordinator
    captured = {}

    async def fake_start(request, retry_parent=None):
        captured["request"] = request
        captured["retry_parent"] = retry_parent
        return "retry-child"

    coordinator.start = fake_start
    response = authed_client.post(f"/api/jobs/{job_id}/retry")
    assert response.status_code == 202, response.text
    assert captured["retry_parent"] == job_id
    assert captured["request"]["plan_id"] == "new-plan"
    assert captured["request"]["ids"] == ["act-pending-replanned"]


def test_download_ids_are_explicit_and_unique(authed_client) -> None:
    empty = authed_client.post("/api/jobs", json={"kind": "download", "plan_id": "p", "ids": []})
    assert empty.status_code == 400
    dup = authed_client.post(
        "/api/jobs", json={"kind": "download", "plan_id": "p", "ids": ["a", "a"]}
    )
    assert dup.status_code == 400


def test_cached_plan_missing_is_404_without_filesystem_scan(authed_client, tmp_path) -> None:
    response = authed_client.get("/api/plans/latest")
    assert response.status_code == 404
    assert not (tmp_path / "lib").exists()


def test_malformed_worker_is_killed_and_failed(tmp_path) -> None:
    script = "import sys,time; sys.stdin.readline(); print('not-json',flush=True); time.sleep(30)"
    client = _client(tmp_path, _worker(script))
    try:
        started = client.post("/api/jobs", json={"kind": "diagnostics", "checks": ["database"]})
        job_id = started.json()["job_id"]
        for _ in range(100):
            snapshot = client.get(f"/api/jobs/{job_id}").json()
            if snapshot["status"] == "failed":
                break
            time.sleep(0.02)
        assert snapshot["status"] == "failed"
        assert snapshot["error"]["code"] == "WORKER_FAILED"
    finally:
        client.__exit__(None, None, None)


def test_worker_stderr_flood_is_drained_and_bounded(tmp_path) -> None:
    script = textwrap.dedent(
        """
        import json,sys
        sys.stdin.readline()
        sys.stderr.write('api_key=topsecret ' + 'x'*300000)
        sys.stderr.flush()
        print(json.dumps({'v':1,'seq':1,'type':'result','result':{'ok':True}}), flush=True)
        """
    )
    client = _client(tmp_path, _worker(script))
    try:
        started = client.post("/api/jobs", json={"kind": "diagnostics", "checks": ["database"]})
        job_id = started.json()["job_id"]
        for _ in range(100):
            snapshot = client.get(f"/api/jobs/{job_id}").json()
            if snapshot["status"] in {"succeeded", "failed"}:
                break
            time.sleep(0.02)
        assert snapshot["status"] == "succeeded"
        assert snapshot["logs"]
        assert all(len(row["line"]) <= 4096 for row in snapshot["logs"])
        assert "topsecret" not in "".join(row["line"] for row in snapshot["logs"])
    finally:
        client.__exit__(None, None, None)


def test_startup_marks_abandoned_jobs_interrupted(tmp_path) -> None:
    from yt_dlp_emby.server.app import create_app
    from yt_dlp_emby.server.job_store import JobStore

    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create("abandoned", "check", {"kind": "check", "items": []})
    store.update("abandoned", status="running", started_at="2026-10-04T00:00:00+00:00")
    store.close()
    with TestClient(create_app(data_dir=tmp_path, environ={})) as client:
        client.post("/api/setup", json={"password": "secretpass"})
        snapshot = client.get("/api/jobs/abandoned").json()
        assert snapshot["status"] == "interrupted"
        assert snapshot["can_retry"] is True


def test_resolve_data_dir(tmp_path) -> None:
    explicit = tmp_path / "explicit"
    explicit.mkdir()
    env_dir = tmp_path / "from-env"
    env_dir.mkdir()
    assert resolve_data_dir(None, {"YT_DLP_EMBY_DATA": str(env_dir)}) == env_dir
    assert resolve_data_dir(explicit, {"YT_DLP_EMBY_DATA": str(env_dir)}) == explicit
