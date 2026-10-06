"""Private JSONL worker entry point. This module is not a public CLI command."""

from __future__ import annotations

import json
import os
import signal
import sys
import threading
from pathlib import Path
from typing import Any

PROTOCOL_VERSION = 1
_LAST_SEQ = 0


class OperationContext:
    def __init__(
        self,
        selected_actions: list[dict[str, Any]],
        emit: Any,
        cached_views: list[dict[str, Any]] | None = None,
    ) -> None:
        self.selected_actions = selected_actions
        self.emit = emit
        self.cached_views = cached_views or []


def _emit(event: dict[str, Any]) -> None:
    print(json.dumps({"v": PROTOCOL_VERSION, **event}, separators=(",", ":")), flush=True)


def main() -> int:
    try:
        raw = sys.stdin.readline(2_097_153)
        if not raw or len(raw) > 2_097_152:
            return 2
        request = json.loads(raw)
        if request.get("v") != PROTOCOL_VERSION or not isinstance(request.get("operation"), str):
            return 2

        def watch_parent() -> None:
            # The parent keeps stdin open while the operation runs. A shutdown
            # frame is an orderly completion; EOF means the coordinator died.
            while True:
                line = sys.stdin.readline()
                if not line:
                    # The coordinator owns this process group. Its disappearance
                    # means nobody can safely supervise the operation anymore;
                    # kill the group synchronously so signal-resistant children
                    # cannot continue mutating media or config after parent loss.
                    try:
                        os.killpg(os.getpgrp(), signal.SIGKILL)
                    except OSError:
                        pass
                    return
                try:
                    if json.loads(line).get("type") == "shutdown":
                        return
                except (ValueError, AttributeError):
                    continue

        threading.Thread(target=watch_parent, name="parent-watch", daemon=True).start()
        data_dir = Path(request["data_dir"])
        environ = request.get("environ") or {}
        op = request["operation"]
        payload = request.get("payload") or {}
        selected_actions = payload.get("selected_actions") or []
        seq = 0
        lock = threading.Lock()

        def emit(event: dict[str, Any]) -> None:
            nonlocal seq
            global _LAST_SEQ
            with lock:
                output = dict(event)
                event_name = output.pop("event", None)
                if event_name and "type" not in output:
                    if event_name in {
                        "progress",
                        "item_steps",
                        "item_done",
                        "episode_progress",
                        "download_progress",
                    }:
                        output["type"] = "progress"
                    else:
                        print(
                            json.dumps({"event": event_name, **output}), file=sys.stderr, flush=True
                        )
                        return
                if output.get("type") not in {"progress", "item_result", "result", "error"}:
                    print(json.dumps(output, default=str), file=sys.stderr, flush=True)
                    return
                if output.get("type") == "progress":
                    target = output.get("target")
                    if isinstance(target, dict):
                        output["target"] = f"{target.get('platform', '')}|{target.get('slug', '')}"
                    output.setdefault("completed", 0)
                    output.setdefault("total", None)
                    output.setdefault("stage", event_name or "operation")
                seq += 1
                _LAST_SEQ = seq
                _emit({"seq": seq, **output})
                if (
                    op == "download"
                    and event_name == "item_done"
                    and output.get("action") in {"downloaded", "skipped_existing"}
                ):
                    execution_id = output.get("id")
                    for action in selected_actions:
                        if (
                            isinstance(action, dict)
                            and action.get("execution_id") == execution_id
                            and isinstance(action.get("id"), str)
                        ):
                            seq += 1
                            _LAST_SEQ = seq
                            _emit(
                                {
                                    "seq": seq,
                                    "type": "item_result",
                                    "identity": {"id": action["id"]},
                                    "result": {
                                        "ok": True,
                                        "action": output.get("action"),
                                        "action_id": action["id"],
                                        "execution_id": execution_id,
                                    },
                                }
                            )

        from yt_dlp_emby.server import services

        if op == "refresh":
            results: list[dict[str, Any]] = []
            for target in payload["items"]:
                target = {**target}
                target["parts"] = payload.get("parts", ["listings", "disk", "sonarr"])
                if payload.get("source_index") is not None:
                    target["source_index"] = payload["source_index"]
                if payload.get("expected_revision") is not None:
                    target["expected_revision"] = payload["expected_revision"]
                emit(
                    {
                        "type": "progress",
                        "stage": "refresh",
                        "target": target,
                        "completed": len(results),
                        "total": len(payload["items"]),
                    }
                )
                try:
                    result = services.refresh_target(data_dir, environ, target, emit=emit)
                    if hasattr(result, "to_dict"):
                        result = result.to_dict()
                    result = {
                        **result,
                        "ok": bool(result.get("ok", True))
                        and result.get("error") is None
                        and bool(result.get("plan")),
                    }
                except Exception as exc:
                    result = {
                        "platform": target.get("platform"),
                        "slug": target.get("slug"),
                        "ok": False,
                        "error": {"code": "SOURCE_FAILED", "message": str(exc)[:300]},
                    }
                results.append(result)
                emit({"type": "item_result", "identity": target, "result": result})
            emit(
                {
                    "type": "result",
                    "result": {"ok": all(bool(x.get("ok")) for x in results), "results": results},
                }
            )
        elif op == "download":
            snapshot = payload.get("plan_snapshot") or {}
            actions = payload.get("selected_actions") or [
                item
                for source in (snapshot.get("sources") or {}).values()
                for item in source.get("items", [])
            ]
            context = OperationContext(actions, emit, payload.get("cached_views"))
            result = services.download_selected(
                data_dir,
                environ,
                payload["plan_id"],
                payload["ids"],
                force=payload.get("force", False),
                create=payload.get("create", False),
                operation_context=context,
            )
            emit(
                {
                    "type": "result",
                    "result": result.to_dict() if hasattr(result, "to_dict") else result,
                }
            )
        elif op == "check":
            check_results: list[dict[str, Any]] = []
            for target in payload["items"]:
                try:
                    report = services.check_target(data_dir, environ, target, emit=emit)
                    report = report.to_dict() if hasattr(report, "to_dict") else report
                    result = {
                        "platform": target.get("platform"),
                        "slug": target.get("slug"),
                        "ok": bool(report.get("ok")),
                        "report": report,
                    }
                except Exception as exc:
                    result = {
                        "platform": target.get("platform"),
                        "slug": target.get("slug"),
                        "ok": False,
                        "error": {"code": "CHECK_FAILED", "message": str(exc)[:300]},
                    }
                check_results.append(result)
                emit({"type": "item_result", "identity": target, "result": result})
            emit(
                {
                    "type": "result",
                    "result": {
                        "ok": all(bool(x.get("ok")) for x in check_results),
                        "results": check_results,
                    },
                }
            )
        elif op == "diagnostics":
            result = services.diagnostics(data_dir, environ, payload["checks"], emit=emit)
            emit(
                {
                    "type": "result",
                    "result": result.to_dict() if hasattr(result, "to_dict") else result,
                }
            )
        else:
            emit(
                {
                    "type": "error",
                    "error": {"code": "WORKER_FAILED", "message": "unknown operation"},
                }
            )
            return 2
        return 0
    except BaseException as exc:
        print(f"worker operation failed: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        try:
            _emit(
                {
                    "v": PROTOCOL_VERSION,
                    "seq": _LAST_SEQ + 1,
                    "type": "error",
                    "error": {"code": "WORKER_FAILED", "message": "worker operation failed"},
                }
            )
        except Exception:
            pass
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
