"""Exercise process ownership and cancellation using real child processes."""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from yt_dlp_emby.server.app import create_app

pytestmark = pytest.mark.web


def _alive(pid: int) -> bool:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text()
        return raw[raw.rfind(")") + 2 :].split()[0] != "Z"
    except FileNotFoundError:
        return False


def _wait_for(predicate, seconds: float = 15) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.025)
    raise AssertionError("process lifecycle condition did not settle")


def _stubborn_child(marker: Path) -> str:
    return (
        "import signal,time,os,pathlib; "
        "signal.signal(signal.SIGINT,signal.SIG_IGN); "
        "signal.signal(signal.SIGTERM,signal.SIG_IGN); "
        f"pathlib.Path({str(marker)!r}).write_text(str(os.getpid())); "
        "time.sleep(60)"
    )


def test_cancel_reaps_worker_descendants_before_next_job(tmp_path: Path) -> None:
    marker = tmp_path / "child.pid"
    child_script = _stubborn_child(marker)
    script = (
        "import sys,subprocess,pathlib,time,json\n"
        "sys.stdin.readline()\n"
        f"child=subprocess.Popen([sys.executable,'-c',{child_script!r}])\n"
        "time.sleep(60)\n"
    )
    with TestClient(
        create_app(
            data_dir=tmp_path,
            environ={},
            worker_command_factory=lambda _: [sys.executable, "-c", script],
        )
    ) as client:
        assert client.post("/api/setup", json={"password": "test-password"}).status_code == 200
        response = client.post("/api/jobs", json={"kind": "diagnostics", "checks": ["worker"]})
        assert response.status_code == 202
        ident = response.json()["job_id"]
        _wait_for(marker.exists)
        child_pid = int(marker.read_text())
        try:
            stopped = client.post(f"/api/jobs/{ident}/cancel")
            assert stopped.status_code == 200, stopped.text
            assert stopped.json()["status"] == "cancelled"
            assert not _alive(child_pid), "cancel returned while descendant can still mutate media"
            assert client.get("/api/jobs").json()["active"] is None
            # Cancelling the terminal job again must preserve its final state.
            assert client.post(f"/api/jobs/{ident}/cancel").json()["status"] == "cancelled"
        finally:
            if _alive(child_pid):
                os.kill(child_pid, signal.SIGKILL)


def test_private_worker_parent_eof_stops_signal_resistant_descendant(tmp_path: Path) -> None:
    marker = tmp_path / "orphan.pid"
    child_script = _stubborn_child(marker)
    # Inject a long-running service in the actual private worker module; transport
    # and its parent watcher remain the production implementation.
    script = (
        "import sys,subprocess,pathlib,time\n"
        "from yt_dlp_emby.server import services,worker\n"
        "def diagnostic(*args,**kwargs):\n"
        f"    child=subprocess.Popen([sys.executable,'-c',{child_script!r}])\n"
        "    time.sleep(60)\n"
        "services.diagnostics=diagnostic\n"
        "sys.exit(worker.main())\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        start_new_session=True,
    )
    child_pid = None
    try:
        request = {
            "v": 1,
            "operation": "diagnostics",
            "data_dir": str(tmp_path),
            "environ": {},
            "payload": {"checks": ["worker"]},
        }
        proc.stdin.write((json.dumps(request) + "\n").encode())
        proc.stdin.flush()
        _wait_for(marker.exists)
        child_pid = int(marker.read_text())
        proc.stdin.close()
        _wait_for(lambda: not _alive(child_pid))
        proc.wait(timeout=3)
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        proc.wait(timeout=3)
        for stream in (proc.stdout, proc.stderr):
            stream.close()
        if child_pid is not None and _alive(child_pid):
            os.kill(child_pid, signal.SIGKILL)
