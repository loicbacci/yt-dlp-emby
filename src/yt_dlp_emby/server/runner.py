"""Async subprocess runner for youtube/dropout CLI jobs."""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import shlex
import signal
import sys
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Deque, Mapping

from yt_dlp_emby.cache import atomic_write_private
from yt_dlp_emby.server.manifests import ALLOWED

logger = logging.getLogger("yt_dlp_emby.server")

MAX_LINES = 10_000
MAX_BYTES = 1_048_576
MAX_LINE_LEN = 8192
MAX_EVENTS = 5_000
MAX_EVENTS_BYTES = 2_097_152
MAX_POLL = 500
RUN_TIMEOUT = 6 * 3600
# Shared with the API layer: 2 segments (whole series) or 3 (one episode).
# Deliberately looser than SxxExx so file-stem slugs with spaces/dots pass.
ITEM_ID_PATTERN = r"^(youtube|dropout)\|[^|]{1,128}(\|[^|]{1,256})?$"
ONLY_ID_RE = re.compile(ITEM_ID_PATTERN)
# events.jsonl poll bounds: stat guard + truncate + per-tick slice.
MAX_EVENTS_FILE_BYTES = 5 * 1024 * 1024
POLL_READ_BYTES = 1024 * 1024
POLL_MAX_LINES = 500
# Legacy suffix denylist, kept for compatibility. The allowlist below is now
# authoritative: VERBOSE/DEBUG/FORCE_REFETCH are simply not allowlisted, so the
# server controls child flags explicitly instead of inheriting them from env.
SCRUB_SUFFIXES = ("VERBOSE", "DEBUG", "FORCE_REFETCH")
# Secret-looking keys are NEVER passed to the CLI child (child env is visible
# via /proc to other local users). Matched case-insensitively on any prefix.
SECRET_KEY_RE = re.compile(r"(?i)(password|token|secret|api[_-]?key)")
# Operational YT_DLP_EMBY_*/YT_EMBY_* suffixes the child is allowed to see.
# The child reads library/old_dir/staging via CLI flags built from these, plus
# EVENTS/ONLY/DATA plumbing. NOTE: SONARR_API_KEY is intentionally absent — an
# env-configured Sonarr key no longer reaches the child; runs use the key from
# data-dir config.toml instead.
CHILD_YT_EMBY_ALLOW = frozenset(
    {
        "EVENTS",
        "ONLY",
        "DATA",
        "CONFIG",
        "LIBRARY",
        "OLD_DIR",
        "STAGING",
        "BENCH_DEST",
        "SHOWS_DIR",
        "COOKIES",
        "SONARR_URL",
        "FFMPEG",
    }
)
CHILD_ENV_ALLOW = {
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "LC_ALL",
    "LC_CTYPE",
    "TERM",
    "TMPDIR",
    "TMP",
    "TEMP",
    "TZ",
    "PYTHONPATH",
    "PYTHONUNBUFFERED",
    "VIRTUAL_ENV",
    "FORCE_COLOR",
    "NO_COLOR",
    "SSL_CERT_FILE",
    "REQUESTS_CA_BUNDLE",
    "CURL_CA_BUNDLE",
    "SSL_CERT_DIR",
    "PYTHONHOME",
    "LD_LIBRARY_PATH",
    "XDG_CACHE_HOME",
    "XDG_CONFIG_HOME",
    "XDG_DATA_HOME",
    "UV_CACHE_DIR",
    "UV_PYTHON",
}
SIGINT_WAIT = 5.0
SIGTERM_WAIT = 2.0
EVENTS_NAME = "events.jsonl"
ONLY_NAME = "download-only.json"
PLAN_NAME = "plan.json"

CommandFactory = Callable[..., list[str]]


@dataclass
class LogLine:
    n: int
    line: str


@dataclass
class RunEvent:
    n: int
    event: dict[str, Any]


@dataclass
class _QueuedJob:
    source: str
    dry_run: bool
    force: bool


@dataclass
class RunState:
    status: str = "idle"
    phase: str = "idle"
    source: str | None = None
    dry_run: bool = False
    force: bool = False
    started_at: str | None = None
    finished_at: str | None = None
    exit_code: int | None = None


_SECRET_RE = re.compile(r"(?i)(api[_-]?key|password|secret|token|authorization)([=:\s]+)(\S+)")


def _redact_line(text: str) -> str:
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}{match.group(2)}***", text)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _elapsed_seconds(started_at: str | None, finished_at: str | None) -> float | None:
    if not started_at:
        return None
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return None
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    if finished_at:
        try:
            finished = datetime.fromisoformat(finished_at)
        except ValueError:
            return None
        if finished.tzinfo is None:
            finished = finished.replace(tzinfo=timezone.utc)
    else:
        finished = datetime.now(timezone.utc)
    return max(0.0, (finished - started).total_seconds())


def _scrub_env(environ: Mapping[str, str]) -> dict[str, str]:
    out: dict[str, str] = {}
    for key, value in environ.items():
        # Secrets first: drop regardless of any allowlist below.
        if SECRET_KEY_RE.search(key):
            continue
        if key in CHILD_ENV_ALLOW or key.startswith("PYTHON"):
            out[key] = value
            continue
        for prefix in ("YT_DLP_EMBY_", "YT_EMBY_"):
            if key.startswith(prefix):
                if key[len(prefix) :] in CHILD_YT_EMBY_ALLOW:
                    out[key] = value
                break
    return out


def default_command(
    source: str,
    manifest_path: Path,
    *,
    dry_run: bool,
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
    if force and source == "dropout" and action == "download":
        argv.append("--force")
    if library:
        argv.extend(["--library", library])
    if old_dir:
        argv.extend(["--old-dir", old_dir])
    if staging and action == "download":
        argv.extend(["--staging", staging])
    return argv


def format_spawn_command(argv: list[str], extra_env: Mapping[str, str] | None = None) -> str:
    parts = [f"{key}={shlex.quote(value)}" for key, value in (extra_env or {}).items()]
    parts.append(shlex.join(argv))
    return "$ " + " ".join(parts)


def sources_for_download(ids: list[str] | None, plan: dict[str, Any]) -> list[str]:
    order = ("dropout", "youtube")
    sources = plan.get("sources") or {}
    if ids is None:
        out: list[str] = []
        for name in order:
            block = sources.get(name)
            if not isinstance(block, dict):
                continue
            if block.get("ok") is False:
                continue
            pending = any(
                item.get("action") in {"download", "replace"} for item in block.get("items") or []
            )
            if pending:
                out.append(name)
        return out
    platforms = {item.split("|", 1)[0] for item in ids}
    return [name for name in order if name in platforms]


def plan_pending_count(plan: dict[str, Any]) -> int:
    total = 0
    for block in (plan.get("sources") or {}).values():
        if not isinstance(block, dict):
            continue
        for item in block.get("items") or []:
            if item.get("action") in {"download", "replace"}:
                total += 1
    return total


def load_plan_file(data_dir: Path) -> dict[str, Any] | None:
    path = data_dir / PLAN_NAME
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


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
        self._event_task: asyncio.Task[None] | None = None
        self._reaper_task: asyncio.Task[None] | None = None
        self._state = RunState()
        self._lines: Deque[LogLine] = deque()
        self._line_bytes = 0
        self._next_n = 1
        self._partial = ""
        self._events: Deque[RunEvent] = deque(maxlen=MAX_EVENTS)
        self._event_bytes = 0
        self._next_event_n = 1
        self._events_path = self.data_dir / EVENTS_NAME
        self._events_offset = 0
        self._events_partial = ""
        self._last_progress: dict[str, Any] | None = None
        self._pending_jobs: list[_QueuedJob] = []
        self._halt_queue = False
        self._only_path: Path | None = None
        self._run_phase = "idle"
        self._maintenance_holders = 0

    async def try_acquire_maintenance(self) -> bool:
        """Atomically fail when a run is active, else hold off new run starts.

        Replaces the check-then-act `snapshot()` status peek: the decision and
        the hold happen under one lock acquisition, and `_start_queue`/`start`
        refuse while any hold is outstanding. Also refuses while queued jobs
        remain so a plan+download chain can't interleave with an edit.
        """
        async with self._lock:
            if self._state.status in {"running", "stopping"}:
                return False
            if self._pending_jobs:
                return False
            self._maintenance_holders += 1
            return True

    async def release_maintenance(self) -> None:
        async with self._lock:
            self._maintenance_holders = max(0, self._maintenance_holders - 1)

    def snapshot(self) -> dict[str, Any]:
        from yt_dlp_emby.server.plan_series import load_live_plan

        plan = load_live_plan(self.data_dir, self._environ)
        plan_summary: dict[str, Any] | None = None
        if plan is not None:
            plan_summary = {
                "generated_at": plan.get("generated_at"),
                "force": plan.get("force"),
                "pending": plan_pending_count(plan),
            }
        return {
            "status": self._state.status,
            "phase": self._state.phase,
            "source": self._state.source,
            "dry_run": self._state.dry_run,
            # Deprecated: the runner never passes --verbose; kept for the web
            # client's runSchema (web/src/types.ts), which requires the key.
            "verbose": False,
            "force": self._state.force,
            "started_at": self._state.started_at,
            "finished_at": self._state.finished_at,
            "elapsed": _elapsed_seconds(self._state.started_at, self._state.finished_at),
            "exit_code": self._state.exit_code,
            "plan": plan_summary,
            "progress": self._last_progress,
        }

    def lines_after(self, after: int) -> list[LogLine]:
        return [item for item in self._lines if item.n > after]

    def events_after(self, after: int) -> list[RunEvent]:
        items = [item for item in self._events if item.n > after]
        return items[:MAX_POLL]

    def _clear_buffer(self) -> None:
        self._lines.clear()
        self._line_bytes = 0
        self._next_n = 1
        self._partial = ""

    def _clear_events(self) -> None:
        self._events.clear()
        self._event_bytes = 0
        self._events_offset = 0
        self._events_partial = ""
        self._last_progress = None
        self._events_path.unlink(missing_ok=True)

    def _append_line(self, text: str) -> None:
        line = _redact_line(text[:MAX_LINE_LEN])
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

    def _append_event(self, payload: dict[str, Any]) -> None:
        encoded = len(json.dumps(payload, separators=(",", ":")).encode("utf-8")) + 1
        while self._events and (
            self._event_bytes + encoded > MAX_EVENTS_BYTES or len(self._events) >= MAX_EVENTS
        ):
            old = self._events.popleft()
            self._event_bytes -= (
                len(json.dumps(old.event, separators=(",", ":")).encode("utf-8")) + 1
            )
        self._events.append(RunEvent(n=self._next_event_n, event=payload))
        self._next_event_n += 1
        self._event_bytes += encoded
        kind = payload.get("event")
        if kind in {"progress", "item_done", "series"}:
            self._last_progress = payload

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

    def _poll_events_file(self) -> None:
        try:
            size = self._events_path.stat().st_size
        except OSError:
            return
        if size > MAX_EVENTS_FILE_BYTES:
            # Bound disk + memory: drop the backlog rather than tail a giant file.
            try:
                with open(self._events_path, "r+b") as handle:
                    handle.truncate(0)
            except OSError:
                return
            self._events_offset = 0
            self._events_partial = ""
            return
        if size < self._events_offset:
            # File was replaced under us; start over instead of seeking past EOF.
            self._events_offset = 0
            self._events_partial = ""
        if size <= self._events_offset:
            return
        try:
            with open(self._events_path, "rb") as handle:
                handle.seek(self._events_offset)
                chunk = handle.read(POLL_READ_BYTES)
        except OSError:
            return
        self._events_offset += len(chunk)
        text = self._events_partial + chunk.decode("utf-8", errors="replace")
        lines = text.split("\n")
        self._events_partial = lines.pop() if lines else ""
        if len(lines) > POLL_MAX_LINES:
            # Offset already advanced: stash the overflow for the next tick.
            rest = lines[POLL_MAX_LINES:]
            lines = lines[:POLL_MAX_LINES]
            self._events_partial = "\n".join(rest) + "\n" + self._events_partial
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._append_event(payload)

    async def _read_stdout(self, proc: asyncio.subprocess.Process) -> None:
        assert proc.stdout is not None
        while True:
            chunk = await proc.stdout.read(4096)
            if not chunk:
                break
            self._feed(chunk.decode("utf-8", errors="replace"))

    async def _watch_events(self) -> None:
        while True:
            async with self._lock:
                if self._proc is None and self._state.status not in {"running", "stopping"}:
                    break
            self._poll_events_file()
            await asyncio.sleep(0.05)

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
        self._poll_events_file()
        if self._state.status not in {"running", "stopping"}:
            return
        stopped = self._state.status == "stopping"
        self._state.status = "exited"
        self._state.phase = "exited"
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
        try:
            code = await asyncio.wait_for(proc.wait(), timeout=RUN_TIMEOUT)
            timed_out = False
        except TimeoutError:
            timed_out = True
            logger.warning("run exceeded RUN_TIMEOUT=%ss; terminating", RUN_TIMEOUT)
            self._signal_pid(proc.pid, signal.SIGTERM)
            try:
                code = await asyncio.wait_for(proc.wait(), timeout=SIGTERM_WAIT)
            except TimeoutError:
                self._signal_pid(proc.pid, signal.SIGKILL)
                code = await proc.wait()
        if timed_out:
            code = 124
        watcher = self._event_task
        if watcher is not None:
            watcher.cancel()
            try:
                await watcher
            except asyncio.CancelledError:
                pass
        self._poll_events_file()
        continue_queue = False
        source = None
        dry_run = False
        only_path = None
        async with self._lock:
            source = self._state.source
            dry_run = self._state.dry_run
            only_path = self._only_path
            self._mark_exited(proc, code)
            continue_queue = (
                not self._halt_queue and bool(self._pending_jobs) and self._state.status == "exited"
            )
        if source in {"dropout", "youtube"}:
            try:
                from yt_dlp_emby.server.plan_series import sync_plan_after_run

                await asyncio.to_thread(
                    sync_plan_after_run,
                    self.data_dir,
                    source,
                    environ=self._environ,
                    dry_run=dry_run,
                    only_path=only_path,
                )
            except Exception as exc:
                logger.debug("plan sync after %s run failed: %s", source, exc)
        if continue_queue:
            await self._start_next_job()

    async def stop(self) -> RunState:
        async with self._lock:
            self._halt_queue = True
            if self._state.status not in {"running", "stopping"}:
                return self._state
            self._state.status = "stopping"
            self._state.phase = "stopping"
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

    def _plan_jobs(self, force: bool) -> list[_QueuedJob]:
        jobs: list[_QueuedJob] = []
        for source in ("dropout", "youtube"):
            if (self.data_dir / ALLOWED[source]).is_file():
                jobs.append(_QueuedJob(source, True, force))
        return jobs

    async def start_plan(self, *, force: bool = False) -> RunState:
        jobs = self._plan_jobs(force)
        if not jobs:
            raise FileNotFoundError("no manifest files on disk")
        return await self._start_queue(jobs, phase="planning", force=force, only_path=None)

    async def start_download(
        self,
        ids: list[str] | None,
        *,
        force: bool = False,
    ) -> RunState:
        plan = load_plan_file(self.data_dir)
        if plan is None:
            raise FileNotFoundError("no plan.json — refresh the queue first")
        platforms = sources_for_download(ids, plan)
        if not platforms:
            raise ValueError("nothing to download in plan")
        jobs = [_QueuedJob(source, False, force) for source in platforms]
        only_path: Path | None = None
        if ids is not None:
            for item in ids:
                if not ONLY_ID_RE.match(str(item)):
                    raise ValueError(f"invalid item id: {item}")
            only_path = self.data_dir / ONLY_NAME
            atomic_write_private(
                only_path,
                json.dumps({"ids": ids}, separators=(",", ":")),
                mode=0o600,
            )
        return await self._start_queue(jobs, phase="downloading", force=force, only_path=only_path)

    async def _start_queue(
        self,
        jobs: list[_QueuedJob],
        *,
        phase: str,
        force: bool,
        only_path: Path | None,
    ) -> RunState:
        async with self._lock:
            if self._state.status in {"running", "stopping"}:
                raise RuntimeError("already running")
            if self._maintenance_holders > 0:
                raise RuntimeError("maintenance in progress")
            self._clear_buffer()
            self._clear_events()
            self._halt_queue = False
            self._only_path = only_path
            self._run_phase = phase
            self._pending_jobs = list(jobs[1:])
            first = jobs[0]
            self._state = RunState(
                status="running",
                phase=phase,
                source=first.source,
                dry_run=first.dry_run,
                force=force,
                started_at=_utc_now(),
            )
            try:
                await self._spawn_locked(first)
            except Exception as exc:
                self._fail_spawn(exc)
                raise
            return self._state

    async def _start_next_job(self) -> None:
        async with self._lock:
            if self._halt_queue or not self._pending_jobs:
                return
            if self._state.status != "exited":
                return
            job = self._pending_jobs.pop(0)
            self._state = RunState(
                status="running",
                phase=self._run_phase,
                source=job.source,
                dry_run=job.dry_run,
                force=self._state.force,
                started_at=_utc_now(),
            )
            try:
                await self._spawn_locked(job)
            except Exception as exc:
                self._fail_spawn(exc)

    def _fail_spawn(self, exc: BaseException) -> None:
        self._proc = None
        self._reader_task = None
        self._event_task = None
        self._reaper_task = None
        self._pending_jobs = []
        self._state.status = "exited"
        self._state.phase = "exited"
        self._state.finished_at = _utc_now()
        self._state.exit_code = 1
        self._append_line(f"error: {exc}")

    async def _spawn_locked(self, job: _QueuedJob) -> None:
        manifest_path = self.data_dir / ALLOWED[job.source]
        if not manifest_path.is_file():
            raise FileNotFoundError(f"manifest not found: {manifest_path.name}")
        env = _scrub_env(self._environ)
        env["PYTHONUNBUFFERED"] = "1"
        env.pop("NO_COLOR", None)
        env["FORCE_COLOR"] = "1"
        env["YT_DLP_EMBY_EVENTS"] = str(self._events_path)
        if self._only_path is not None and not job.dry_run:
            env["YT_DLP_EMBY_ONLY"] = str(self._only_path)
        else:
            env.pop("YT_DLP_EMBY_ONLY", None)
        argv = self._command_factory(
            job.source,
            manifest_path,
            dry_run=job.dry_run,
            force=job.force,
            action="download",
            library=env.get("YT_DLP_EMBY_LIBRARY") or env.get("YT_EMBY_LIBRARY"),
            old_dir=env.get("YT_DLP_EMBY_OLD_DIR") or env.get("YT_EMBY_OLD_DIR"),
            staging=env.get("YT_DLP_EMBY_STAGING") or env.get("YT_EMBY_STAGING"),
        )
        extra_env = {}
        only = env.get("YT_DLP_EMBY_ONLY")
        if only:
            extra_env["YT_DLP_EMBY_ONLY"] = only
        self._append_line(format_spawn_command(argv, extra_env))
        self._proc = await asyncio.create_subprocess_exec(
            *argv,
            cwd=str(self.data_dir),
            env=env,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            start_new_session=True,
        )
        self._reader_task = asyncio.create_task(self._read_stdout(self._proc))
        self._event_task = asyncio.create_task(self._watch_events())
        self._reaper_task = asyncio.create_task(self._reap(self._proc))

    async def start(
        self,
        source: str,
        *,
        dry_run: bool = False,
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
        phase = "planning" if use_dry else "downloading"
        job = _QueuedJob(source, use_dry, use_force)
        async with self._lock:
            if self._state.status in {"running", "stopping"}:
                raise RuntimeError("already running")
            if self._maintenance_holders > 0:
                raise RuntimeError("maintenance in progress")
            self._clear_buffer()
            self._clear_events()
            self._halt_queue = False
            self._only_path = None
            self._pending_jobs = []
            self._run_phase = phase
            self._state = RunState(
                status="running",
                phase=phase,
                source=source,
                dry_run=use_dry,
                force=use_force,
                started_at=_utc_now(),
            )
            try:
                await self._spawn_locked(job)
            except Exception as exc:
                self._fail_spawn(exc)
                raise
            return self._state
