"""Exclusive coordinator for persisted, isolated worker jobs."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import signal
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

from yt_dlp_emby.server.job_store import TERMINAL, JobStore, utc_now

SECRET_RE = re.compile(
    r"(?i)([\"']?(?:api[_-]?key|password|secret|token|authorization)[\"']?\s*[:=]\s*[\"']?)([^\s,\"'}]+)"
)
BEARER_RE = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)([^\s,\"']+)")
TIMEOUTS = {"refresh": 300, "download": 21600, "check": 300, "diagnostics": 300}


def redact(line: str, secrets: tuple[str, ...] = ()) -> str:
    line = BEARER_RE.sub(r"\1***", line)
    line = SECRET_RE.sub(r"\1***", line)
    for secret in secrets:
        if len(secret) >= 4:
            line = line.replace(secret, "***")
    return line[:4096]


def _sanitize(value: Any, secrets: tuple[str, ...]) -> Any:
    if isinstance(value, str):
        return redact(value, secrets)
    if isinstance(value, list):
        return [_sanitize(item, secrets) for item in value]
    if isinstance(value, dict):
        return {
            key: (
                "***"
                if re.search(r"(?i)(password|token|secret|api[_-]?key|authorization)", str(key))
                else _sanitize(item, secrets)
            )
            for key, item in value.items()
        }
    return value


class JobConflict(RuntimeError):
    def __init__(self, job_id: str) -> None:
        super().__init__(f"job {job_id} is active")
        self.job_id = job_id


class JobCoordinator:
    def __init__(
        self,
        data_dir: Path,
        environ: Mapping[str, str],
        store: JobStore,
        worker_command_factory: Callable[[dict[str, Any]], Sequence[str]] | None = None,
    ) -> None:
        self.data_dir = data_dir
        self.environ = dict(environ)
        self._secrets = tuple(
            value
            for key, value in self.environ.items()
            if re.search(r"(?i)(password|token|secret|api[_-]?key|cookie)", key) and value
        )
        self.store = store
        self.worker_command_factory = worker_command_factory
        self._lock = asyncio.Lock()
        self._task: asyncio.Task[None] | None = None
        self._cancel = asyncio.Event()
        self._proc: asyncio.subprocess.Process | None = None

    async def recover(self) -> None:
        """Stop only workers whose PID and Linux start identity still match."""
        for row in self.store.active_workers():
            pid = int(row["worker_pid"])
            if row.get("worker_start") and _process_start(pid) == row["worker_start"]:
                for sig, wait in ((signal.SIGTERM, 2), (signal.SIGKILL, 0)):
                    try:
                        os.killpg(pid, sig)
                    except ProcessLookupError:
                        break
                    deadline = asyncio.get_running_loop().time() + wait
                    while (
                        wait
                        and _process_group_exists(pid)
                        and asyncio.get_running_loop().time() < deadline
                    ):
                        await asyncio.sleep(0.05)
                    if not _process_group_exists(pid):
                        break
        self.store.recover()

    async def start(self, request: dict[str, Any], retry_parent: str | None = None) -> str:
        async with self._lock:
            active, _, _ = self.store.list_jobs(limit=1)
            if active:
                raise JobConflict(str(active["id"]))
            job_id = uuid.uuid4().hex
            self.store.create(job_id, request["kind"], request, retry_parent)
            if request["kind"] == "refresh":
                for target in request.get("items", []):
                    self.store.item(job_id, json.dumps(target, sort_keys=True), target, "queued")
            elif request["kind"] == "download":
                for selected_id in request.get("ids", []):
                    identity = {"id": selected_id}
                    self.store.item(
                        job_id, json.dumps(identity, sort_keys=True), identity, "queued"
                    )
            self._cancel = asyncio.Event()
            self._task = asyncio.create_task(self._run(job_id, request), name=f"job-{job_id}")
            return job_id

    async def cancel(self, job_id: str) -> None:
        job = self.store.get(job_id)
        if job is None:
            raise KeyError(job_id)
        if job["status"] in TERMINAL:
            return
        self.store.update(job_id, status="stopping")
        self._cancel.set()
        proc = self._proc
        if proc is not None:
            await self._terminate(proc)
        if self._task is not None:
            await asyncio.gather(self._task, return_exceptions=True)

    async def shutdown(self) -> None:
        if self._task is not None and not self._task.done():
            self._cancel.set()
            if self._proc:
                await self._terminate(self._proc)
            await asyncio.gather(self._task, return_exceptions=True)

    async def _run(self, job_id: str, request: dict[str, Any]) -> None:
        self.store.update(job_id, status="running", started_at=utc_now())
        if request.get("kind") != "refresh":
            status, result, error = await self._run_worker(job_id, request)
        else:
            results: list[dict[str, Any]] = []
            status = "succeeded"
            error = None
            targets = request.get("items", [])
            for index, target in enumerate(targets):
                item_status, item_result, item_error = await self._run_worker(
                    job_id,
                    {**request, "items": [target]},
                    progress_offset=index,
                    progress_total=len(targets),
                )
                if item_status != "cancelled":
                    self.store.update(
                        job_id,
                        progress_json=json.dumps(
                            {
                                "stage": "refresh",
                                "target": f"{target.get('platform', '')}|{target.get('slug', '')}",
                                "completed": index + 1,
                                "total": len(targets),
                            }
                        ),
                    )
                if isinstance(item_result, dict):
                    results.extend(item_result.get("results", []))
                elif item_error:
                    results.append(
                        {
                            "platform": target.get("platform"),
                            "slug": target.get("slug"),
                            "ok": False,
                            "error": item_error,
                        }
                    )
                if item_status == "cancelled":
                    status = "cancelled"
                    break
                if item_status != "succeeded":
                    status = "failed"
                    error = item_error or {"code": "SOURCE_FAILED", "message": "refresh failed"}
            result = {
                "ok": bool(results) and all(row.get("ok") for row in results),
                "results": results,
            }
            if status == "succeeded" and not result["ok"]:
                status = "failed"
        self.store.update(
            job_id,
            status=status,
            finished_at=utc_now(),
            result_json=json.dumps(_sanitize(result, self._secrets), default=str)
            if result is not None
            else None,
            error_json=json.dumps(_sanitize(error, self._secrets), default=str)
            if error is not None
            else None,
        )
        self.store.retain()

    async def _run_worker(
        self,
        job_id: str,
        request: dict[str, Any],
        *,
        progress_offset: int = 0,
        progress_total: int | None = None,
    ) -> tuple[str, Any, Any]:
        self.store.update(job_id, status="running")
        seq = 0
        logn = self.store.latest_log_cursor(job_id)
        result: Any = None
        refresh_items: list[dict[str, Any]] = []
        last_progress_at = 0.0
        error: Any = None
        protocol_error: Exception | None = None
        status = "failed"
        try:
            payload = {k: v for k, v in request.items() if k != "kind"}
            if request["kind"] == "refresh":
                for target in payload.get("items", []):
                    cached = self.store.get_view(target["platform"], target["slug"])
                    if cached:
                        inputs = cached.get("inputs") or {}
                        view = inputs.get("view", inputs) if isinstance(inputs, dict) else {}
                        disk = view.get("disk") if isinstance(view, dict) else None
                        if isinstance(disk, dict) and disk.get("mount_identity"):
                            target["expected_mount_identity"] = disk["mount_identity"]
            if request["kind"] == "check":
                for target in payload.get("items", []):
                    cached = self.store.get_view(target["platform"], target["slug"])
                    if cached:
                        inputs = cached.get("inputs") or {}
                        view = inputs.get("view", inputs) if isinstance(inputs, dict) else {}
                        if isinstance(view, dict):
                            target["cached_view"] = view
            if request["kind"] == "download":
                payload["plan_snapshot"] = {
                    "plan_id": payload.get("plan_id"),
                    "sources": {},
                }
                for row in payload.get("selected_actions", []):
                    platform = str(row.get("platform") or "")
                    payload["plan_snapshot"]["sources"].setdefault(platform, {"items": []})[
                        "items"
                    ].append(row)
            worker_request = {
                "v": 1,
                "operation": request["kind"],
                "data_dir": str(self.data_dir),
                "environ": _worker_environ(self.environ),
                "payload": payload,
            }
            argv = (
                list(self.worker_command_factory(worker_request))
                if self.worker_command_factory
                else [sys.executable, "-m", "yt_dlp_emby.server.worker"]
            )
            proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                cwd=str(self.data_dir),
                env=_worker_env(),
                limit=1_048_576,
            )
            self._proc = proc
            self.store.update(job_id, worker_pid=proc.pid, worker_start=_process_start(proc.pid))
            if self._cancel.is_set():
                await self._terminate(proc)
                status = "cancelled"
                return status, result, error
            assert proc.stdin and proc.stdout and proc.stderr
            worker_stdin, worker_stdout, worker_stderr = proc.stdin, proc.stdout, proc.stderr
            worker_stdin.write((json.dumps(worker_request, separators=(",", ":")) + "\n").encode())
            await worker_stdin.drain()

            async def read_stdout() -> None:
                nonlocal seq, logn, result, error, protocol_error, last_progress_at
                while True:
                    try:
                        line = await worker_stdout.readline()
                    except Exception as exc:
                        protocol_error = exc
                        return
                    if not line:
                        return
                    if len(line) > 1_048_576:
                        protocol_error = ValueError("worker output line too large")
                        return
                    try:
                        event = json.loads(line)
                        if (
                            not isinstance(event, dict)
                            or event.get("v") != 1
                            or event.get("seq") != seq + 1
                        ):
                            raise ValueError("invalid worker sequence")
                        seq += 1
                        kind = event.get("type")
                        if kind == "progress":
                            if not isinstance(event.get("stage"), str):
                                raise ValueError("invalid progress stage")
                            if (
                                not isinstance(event.get("completed"), int)
                                or event["completed"] < 0
                            ):
                                raise ValueError("invalid progress count")
                            if event.get("total") is not None and (
                                not isinstance(event.get("total"), int) or event["total"] < 0
                            ):
                                raise ValueError("invalid progress total")
                            progress = {
                                k: event[k]
                                for k in ("stage", "target", "completed", "total", "item")
                                if k in event
                            }
                            target_value = progress.get("target")
                            if isinstance(target_value, dict):
                                progress["target"] = (
                                    f"{target_value.get('platform', '')}|{target_value.get('slug', '')}"
                                )
                            if "completed" in progress:
                                progress["completed"] += progress_offset
                            if progress_total is not None:
                                progress["total"] = progress_total
                            now = time.monotonic()
                            if now - last_progress_at >= 0.25:
                                self.store.update(
                                    job_id,
                                    progress_json=json.dumps(_sanitize(progress, self._secrets)),
                                )
                                last_progress_at = now
                        elif kind == "item_result":
                            ident = event.get("identity")
                            if not isinstance(ident, dict):
                                raise ValueError("invalid item identity")
                            ident = _sanitize(ident, self._secrets)
                            raw_result = event.get("result")
                            if not isinstance(raw_result, dict):
                                raise ValueError("invalid item result")
                            item_result = _sanitize(raw_result, self._secrets)
                            if request["kind"] == "refresh" and isinstance(item_result, dict):
                                item_result = await self._publish_refresh_result(item_result, ident)
                                refresh_items.append(item_result)
                            self.store.item(
                                job_id,
                                json.dumps(ident, sort_keys=True),
                                ident,
                                "succeeded"
                                if not (
                                    isinstance(item_result, dict) and item_result.get("ok") is False
                                )
                                else "failed",
                                item_result,
                            )
                        elif kind == "result":
                            result = _sanitize(event.get("result"), self._secrets)
                            if request["kind"] == "refresh":
                                result = {
                                    "ok": all(bool(item.get("ok")) for item in refresh_items),
                                    "results": refresh_items,
                                }
                        elif kind == "error":
                            if not isinstance(event.get("error"), dict):
                                raise ValueError("invalid worker error")
                            error = _sanitize(event.get("error"), self._secrets)
                        else:
                            raise ValueError("unknown worker event")
                    except Exception as exc:
                        protocol_error = exc
                        return

            async def read_stderr() -> None:
                nonlocal logn
                pending = bytearray()
                while True:
                    block = await worker_stderr.read(4096)
                    if not block:
                        if pending:
                            logn += 1
                            self.store.append_log(
                                job_id,
                                logn,
                                redact(
                                    pending.decode("utf-8", "replace").rstrip("\r\n"), self._secrets
                                ),
                            )
                        return
                    pending.extend(block)
                    while b"\n" in pending:
                        line, _, rest = pending.partition(b"\n")
                        pending = bytearray(rest)
                        logn += 1
                        self.store.append_log(
                            job_id,
                            logn,
                            redact(
                                line[:4096].decode("utf-8", "replace").rstrip("\r"), self._secrets
                            ),
                        )
                    if len(pending) > 4096:
                        logn += 1
                        self.store.append_log(
                            job_id,
                            logn,
                            redact(
                                pending[:4096].decode("utf-8", "replace") + " …[truncated]",
                                self._secrets,
                            ),
                        )
                        pending.clear()

            stdout_task = asyncio.create_task(read_stdout())
            stderr_task = asyncio.create_task(read_stderr())
            timeout = TIMEOUTS.get(request["kind"], 300)
            wait_task = asyncio.create_task(proc.wait())
            drain_task = asyncio.gather(stdout_task, stderr_task)
            deadline = asyncio.get_running_loop().time() + timeout
            try:
                done, _ = await asyncio.wait(
                    {wait_task, stdout_task}, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                if stdout_task in done and protocol_error is not None and not wait_task.done():
                    await self._terminate(proc)
                else:
                    remaining = max(0.001, deadline - asyncio.get_running_loop().time())
                    await asyncio.wait_for(wait_task, timeout=remaining)
                    remaining = max(0.001, deadline - asyncio.get_running_loop().time())
                    await asyncio.wait_for(asyncio.shield(drain_task), timeout=remaining)
            except TimeoutError:
                error = {"code": "SOURCE_TIMEOUT", "message": "job timed out"}
                await self._terminate(proc)
            await drain_task
            worker_stdin.close()
            await worker_stdin.wait_closed()
            if protocol_error:
                raise protocol_error
            if self._cancel.is_set():
                status = "cancelled"
            elif proc.returncode != 0 or error is not None:
                status = "failed"
                if error is None:
                    error = {"code": "WORKER_FAILED", "message": "worker failed"}
            elif result is None:
                status = "failed"
                error = {"code": "WORKER_FAILED", "message": "worker returned no result"}
            elif isinstance(result, dict) and result.get("ok") is False:
                status = "failed"
            else:
                status = "succeeded"
        except asyncio.CancelledError:
            status = "cancelled"
        except Exception:
            status = "failed"
            error = {"code": "WORKER_FAILED", "message": "worker protocol or startup failed"}
        finally:
            self._proc = None
            result = _sanitize(result, self._secrets)
            error = _sanitize(error, self._secrets)
        return status, result, error

    async def _publish_refresh_result(
        self, item: dict[str, Any], identity: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        from yt_dlp_emby.server.services import (
            apply_refresh_updates,
            current_configuration_revision,
            plan_variant,
        )

        target = item.get("target") or {
            "platform": item.get("platform"),
            "slug": item.get("slug"),
        }
        view, plan = item.get("view"), item.get("plan")
        if not isinstance(target, dict) or not isinstance(view, dict) or not isinstance(plan, dict):
            return item
        platform, slug = str(target.get("platform") or ""), str(target.get("slug") or "")
        try:
            update = item.get("config_updates") or {}
            observed_revision = str(view.get("config_revision") or "")
            live_revision = await asyncio.to_thread(
                current_configuration_revision, self.data_dir, self.environ, platform, slug
            )
            if observed_revision != live_revision:
                raise ValueError("configuration changed during refresh")
            if update:
                new_hash = await asyncio.to_thread(apply_refresh_updates, self.data_dir, update)
                view["manifest_revision"] = new_hash
                view["config_revision"] = await asyncio.to_thread(
                    current_configuration_revision, self.data_dir, self.environ, platform, slug
                )
                plan = plan_variant(view)
                view["plan_id"] = plan["plan_id"]
                item["plan"] = plan
                item["ok"] = True
                item["error"] = None
            source_index = (identity or {}).get("source_index")
            if isinstance(source_index, int):
                prior = self.store.get_view(platform, slug)
                prior_inputs = (prior or {}).get("inputs") or {}
                prior_view = prior_inputs.get("view", {}) if isinstance(prior_inputs, dict) else {}
                if (
                    prior
                    and prior.get("freshness") == "ready"
                    and isinstance(prior_view, dict)
                    and prior_view.get("config_revision") == view.get("config_revision")
                    and prior_view.get("listings_complete", True)
                ):
                    old_rows = [
                        row
                        for row in prior_view.get("provider_listings", [])
                        if isinstance(row, dict) and row.get("source_index") != source_index
                    ]
                    fresh_rows = [
                        row for row in view.get("provider_listings", []) if isinstance(row, dict)
                    ]
                    view["provider_listings"] = old_rows + fresh_rows
                    view["listings_complete"] = True
                    refreshed = set(prior_view.get("refreshed_sources", []))
                    refreshed.update(view.get("refreshed_sources", [source_index]))
                    view["refreshed_sources"] = sorted(refreshed)
                    view["listing_revision"] = hashlib.sha256(
                        json.dumps(view["provider_listings"], sort_keys=True).encode()
                    ).hexdigest()
                    plan = plan_variant(view)
                    view["plan_id"] = plan["plan_id"]
                    item["plan"] = plan
                else:
                    view["listings_complete"] = False
                    view.setdefault("refreshed_sources", [source_index])
            if item.get("ok") and (view.get("disk") or {}).get("status") == "ready":
                attempt = utc_now()
                self.store.put_view(
                    platform,
                    slug,
                    {"view": view},
                    plan,
                    str(plan.get("revision", "")),
                    "ready",
                    attempt,
                    attempt,
                )
            elif item.get("error"):
                item["error"] = _sanitize(item["error"], self._secrets)
                self.store.record_view_attempt(platform, slug, item["error"])
        except Exception as exc:
            item["ok"] = False
            item["error"] = _sanitize(
                {"code": "CONFIG_CHANGED", "message": str(exc)[:300]}, self._secrets
            )
            self.store.record_view_attempt(platform, slug, item["error"])
        return item

    async def _terminate(self, proc: asyncio.subprocess.Process) -> None:
        for sig, wait in ((signal.SIGINT, 5), (signal.SIGTERM, 2), (signal.SIGKILL, 0)):
            try:
                os.killpg(proc.pid, sig)
            except ProcessLookupError:
                if proc.returncode is not None:
                    break
            if wait:
                deadline = asyncio.get_running_loop().time() + wait
                while asyncio.get_running_loop().time() < deadline:
                    if not _process_group_exists(proc.pid):
                        break
                    await asyncio.sleep(0.1)
        if proc.returncode is None:
            await proc.wait()
        # SIGKILL is also sent to descendants that outlived their leader.
        deadline = asyncio.get_running_loop().time() + 2
        while _process_group_exists(proc.pid) and asyncio.get_running_loop().time() < deadline:
            await asyncio.sleep(0.05)


def _process_start(pid: int) -> str | None:
    try:
        raw = Path(f"/proc/{pid}/stat").read_text(encoding="ascii")
        tail = raw[raw.rfind(")") + 2 :].split()
        return tail[19]
    except (OSError, IndexError):
        return None


def _process_group_exists(pgid: int) -> bool:
    try:
        os.killpg(pgid, 0)
        return True
    except ProcessLookupError:
        return False


def _worker_env() -> dict[str, str]:
    allowed = {
        "PATH",
        "HOME",
        "LANG",
        "LC_ALL",
        "LC_CTYPE",
        "TMPDIR",
        "TMP",
        "TEMP",
        "TZ",
        "VIRTUAL_ENV",
        "PYTHONUNBUFFERED",
        "SSL_CERT_FILE",
        "SSL_CERT_DIR",
        "LD_LIBRARY_PATH",
    }
    env = {key: value for key, value in os.environ.items() if key in allowed}
    src = str(Path(__file__).resolve().parents[2])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (src, os.environ.get("PYTHONPATH"))))
    env["PYTHONUNBUFFERED"] = "1"
    return env


def _worker_environ(environ: Mapping[str, str]) -> dict[str, str]:
    allowed = {"SONARR_URL", "SONARR_API_KEY", "YOUTUBE_COOKIES", "DROPOUT_COOKIES"}
    output: dict[str, str] = {}
    for key, value in environ.items():
        suffix = key.removeprefix("YT_DLP_EMBY_").removeprefix("YT_EMBY_")
        if key in allowed or (
            key.startswith(("YT_DLP_EMBY_", "YT_EMBY_"))
            and suffix not in {"DEBUG", "VERBOSE", "FORCE_REFETCH"}
        ):
            output[key] = value
    return output
