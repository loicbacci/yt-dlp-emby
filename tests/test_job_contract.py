"""Sanitized job, plan and library fixtures shared with the browser tests."""

from __future__ import annotations

import json
from pathlib import Path

from yt_dlp_emby.server.job_models import JobList, JobSnapshot
from yt_dlp_emby.server.jobs import redact

FIXTURES = Path(__file__).parent / "fixtures" / "job-contract"


def test_shared_job_snapshots_validate() -> None:
    fixtures = json.loads((FIXTURES / "snapshots.json").read_text(encoding="utf-8"))
    for key in ("queued", "running", "succeeded", "partial_failure", "cancelled", "interrupted"):
        JobSnapshot.model_validate(fixtures[key])
    assert fixtures["stale_plan"]["readiness"] == "stale"
    assert fixtures["unavailable_library"]["series_exists"] is None
    request_contract = json.loads((FIXTURES / "requests.json").read_text(encoding="utf-8"))
    assert request_contract["refresh_start"] == {"job_id": "job-queued", "status": "queued"}
    JobList.model_validate(request_contract["jobs"])


def test_log_redaction_covers_json_bearer_and_known_values() -> None:
    value = '"api_key": "topsecret", Authorization: Bearer opaque-token'
    cleaned = redact(value, ("topsecret", "opaque-token"))
    assert "topsecret" not in cleaned and "opaque-token" not in cleaned
    assert cleaned.count("***") >= 2
