"""Async subprocess runner for youtube/dropout CLI jobs."""

from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Mapping

from yt_dlp_emby.server.manifests import ALLOWED

MAX_LINES = 10_000
MAX_BYTES = 1_048_576
MAX_LINE_LEN = 8192
SCRUB_SUFFIXES = ("VERBOSE", "DEBUG", "FORCE_REFETCH")
SIGINT_WAIT = 5.0
SIGTERM_WAIT = 2.0

CommandFactory = Callable[..., list[str]]


@dataclass
class LogLine:
    n: int
    line: str


@dataclass
class RunState:
    status: str = "idle"
    source: str | None = None
    dry_run: bool = False
    verbose: bool = False
    force: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _scrub_env(environ: Mapping[str, str]) -> dict[str, str]:
    out = dict(environ)
    for key in list(out):
        for prefix in ("YT_DLP_EMBY_", "YT_EMBY_"):
            if key.startswith(prefix) and key[len(prefix) :] in SCRUB_SUFFIXES:
                del out[key]
    return out


def default_command(
    source: str,
    manifest_path: Path,
    *,
    dry_run: bool,
    verbose: bool,
    force: bool,
    action: str = "download",
    library: str | None,
    old_dir: str | None,
    staging: str | None,
) -> list[str]:
    if action not in {"download", "layout", "check"}:
        action = "download"
    argv = [
        sys.executable,
        "-m",
        "yt_dlp_emby",
        source,
    ]
    if source == "dropout":
        argv.append(action)
    argv.extend(["--manifest", str(manifest_path)])
    if dry_run and action == "download":
        argv.append("--dry-run")
    if verbose:
        argv.append("--verbose")
    if force and source == "dropout" and action == "download":
        argv.append("--force")
    if library:
        argv.extend(["--library", library])
    if old_dir:
        argv.extend(["--old-dir", old_dir])
    if staging and action == "download":
        argv.extend(["--staging", staging])
    return argv


class RunManager:
    def __init__(
        self,
        data_dir: Path,
        *,
        environ: Mapping[str, str] | None = None,
        command_factory: CommandFactory | None = None,
    ) -> None:
        self.data_dir = data_dir
        self._environ = dict(environ or os.environ)
        self._command_factory = command_factory or default_command
        self._lock = asyncio.Lock()
        self._proc: asyncio.subprocess.Process | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._reaper_task: asyncio.Task[None] | None = None
        self._state = RunState()
        self._lines: Deque[LogLine] = deque()
        self._line_bytes = 0
        self._next_n = 1
        self._partial = ""

    def snapshot(self) -> dict[str, Any]:
        return {
            "status": self._state.status,
            "source": self._state.source,
            "dry_run": self._state.dry_run,
            "verbose": self._state.verbose,
            "force": self._state.force,
            "started_at": self._state.started_at,
            "finished_at": self._state.finished_at,
            "exit_code": self._state.exit_code,
        }

    def lines_after(self, after: int) -> list[LogLine]:
        return [item for item in self._lines if item.n > after]

    def _clear_buffer(self) -> None:
        self._lines.clear()
        self._line_bytes = 0
        self._next_n = 1
        self._partial = ""

    def _append_line(self, text: str) -> None:
        line = text[:MAX_LINE_LEN]
        size = len(line.encode("utf-8")) + 1
        while self._lines and self._line_bytes + size > MAX_BYTES:
            old = self._lines.popleft()
            self._line_bytes -= len(old.line.encode("utf-8")) + 1
        while len(self._lines) >= MAX_LINES:
            old = self._lines.popleft()
            self._line_bytes -= len(old.line.encode("utf-8")) + 1
        self._lines.append(LogLine(n=self._next_n, line=line))
        self._next_n += 1
        self._line_bytes += size

    def _feed(self, chunk: str) -> None:
        self._partial += chunk
        while "\n" in self._partial:
            line, self._partial = self._partial.split("\n", 1)
            if line.endswith("\r"):
                line = line[:-1]
            self._append_line(line)
        if self._partial and "\n" not in self._partial and len(self._partial) > MAX_LINE_LEN:
            self._append_line(self._partial)
            self._partial = ""

    async def _read_stdout(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            self._feed(chunk.decode("utf-8", errors="replace"))

    def _signal_pid(self, pid: int | None, sig: signal.Signals) -> None:
        if pid is None:
            return
        try:
            os.killpg(pid, sig)
        except ProcessLookupError:
            pass
        except PermissionError:
            try:
                os.kill(pid, sig)
            except ProcessLookupError:
                pass

    def _mark_exited(self, proc: asyncio.subprocess.Process, code: int | None) -> None:
        if self._proc is not proc:
            return
        self._proc = None
        self._reader_task = None
        if self._state.status not in {"running", "stopping"}:
            return
        stopped = self._state.status == "stopping"
        self._state.status = "exited"
        self._state.finished_at = _utc_now()
        if code is None:
            code = -1
        if stopped and code != 0:
            self._state.exit_code = 130
        else:
            self._state.exit_code = code

    async def _reap(self, proc: asyncio.subprocess.Process) -> None:
        reader = self._reader_task
        if reader is not None:
            try:
                await reader
            except asyncio.CancelledError:
                pass
        if self._partial:
            self._append_line(self._partial)
            self._partial = ""
        code = await proc.wait()
        async with self._lock:
            self._mark_exited(proc, code)

    async def stop(self) -> RunState:
        async with self._lock:
            if self._state.status not in {"running", "stopping"}:
                return self._state
            self._state.status = "stopping"
            proc = self._proc
            reaper = self._reaper_task
            pid = proc.pid if proc is not None else None
        if proc is None:
            return self._state
        self._signal_pid(pid, signal.SIGINT)
        if reaper is None:
            async with self._lock:
                self._mark_exited(proc, 130)
            return self._state
        try:
            await asyncio.wait_for(asyncio.shield(reaper), timeout=SIGINT_WAIT)
        except TimeoutError:
            self._signal_pid(pid, signal.SIGTERM)
            try:
                await asyncio.wait_for(asyncio.shield(reaper), timeout=SIGTERM_WAIT)
            except TimeoutError:
                self._signal_pid(pid, signal.SIGKILL)
                await reaper
        return self._state

    async def start(
        self,
        source: str,
        *,
        dry_run: bool = False,
        verbose: bool = False,
        force: bool = False,
        action: str = "download",
    ) -> RunState:
        if source not in ALLOWED:
            raise ValueError(f"unknown source: {source}")
        if action not in {"download", "layout", "check"}:
            raise ValueError(f"unknown action: {action}")
        if source == "youtube" and action != "download":
            raise ValueError("action is not valid for youtube")
        if source == "youtube" and force:
            raise ValueError("force is not valid for youtube")
        if source == "dropout" and force and action != "download":
            raise ValueError("force is not valid for layout or check")
        manifest_path = self.data_dir / ALLOWED[source]
        if not manifest_path.is_file():
            raise FileNotFoundError(f"manifest not found: {manifest_path.name}")

        use_dry = dry_run and action == "download"
        use_force = force and action == "download"
        async with self._lock:
            if self._state.status in {"running", "stopping"}:
                raise RuntimeError("already running")

            self._clear_buffer()
            self._state = RunState(
                status="running",
                source=source,
                dry_run=use_dry,
                verbose=verbose,
                force=use_force,
                started_at=_utc_now(),
            )

            env = _scrub_env(self._environ)
            env["PYTHONUNBUFFERED"] = "1"
            env.pop("NO_COLOR", None)
            env["FORCE_COLOR"] = "1"
            argv = self._command_factory(
                source,
                manifest_path,
                dry_run=use_dry,
                verbose=verbose,
                force=use_force,
                action=action,
                library=env.get("YT_DLP_EMBY_LIBRARY") or env.get("YT_EMBY_LIBRARY"),
                old_dir=env.get("YT_DLP_EMBY_OLD_DIR") or env.get("YT_EMBY_OLD_DIR"),
                staging=env.get("YT_DLP_EMBY_STAGING") or env.get("YT_EMBY_STAGING"),
            )
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=str(self.data_dir),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                start_new_session=True,
            )
            self._reader_task = asyncio.create_task(self._read_stdout(self._proc))
            self._reaper_task = asyncio.create_task(self._reap(self._proc))
            return self._state
