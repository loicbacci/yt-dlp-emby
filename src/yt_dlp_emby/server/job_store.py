"""SQLite persistence for job state, completion records, logs and cached views."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

TERMINAL = {"succeeded", "failed", "cancelled", "interrupted"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class JobStore:
    """Single-process writer with each public operation committed atomically."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, timeout=10, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("PRAGMA busy_timeout=10000")
        self._db.executescript(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations(version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, kind TEXT NOT NULL, request_json TEXT NOT NULL,
              status TEXT NOT NULL, created_at TEXT NOT NULL, started_at TEXT,
              finished_at TEXT, progress_json TEXT, result_json TEXT, error_json TEXT,
              worker_pid INTEGER, worker_start TEXT, retry_parent TEXT,
              FOREIGN KEY(retry_parent) REFERENCES jobs(id) ON DELETE SET NULL);
            CREATE INDEX IF NOT EXISTS jobs_status_created ON jobs(status, created_at DESC);
            CREATE TABLE IF NOT EXISTS job_items(
              job_id TEXT NOT NULL, item_key TEXT NOT NULL, identity_json TEXT NOT NULL,
              state TEXT NOT NULL, result_json TEXT, completed_at TEXT,
              PRIMARY KEY(job_id,item_key), FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS job_logs(
              job_id TEXT NOT NULL, n INTEGER NOT NULL, ts TEXT NOT NULL, line TEXT NOT NULL,
              PRIMARY KEY(job_id,n), FOREIGN KEY(job_id) REFERENCES jobs(id) ON DELETE CASCADE);
            CREATE TABLE IF NOT EXISTS series_views(
              platform TEXT NOT NULL, slug TEXT NOT NULL, inputs_json TEXT NOT NULL,
              plan_json TEXT NOT NULL, revision TEXT NOT NULL, freshness TEXT NOT NULL,
              last_attempt_at TEXT, last_success_at TEXT, error_json TEXT,
              PRIMARY KEY(platform,slug));
            INSERT OR IGNORE INTO schema_migrations(version,applied_at) VALUES(1,CURRENT_TIMESTAMP);
            """
        )
        self._db.commit()

    def close(self) -> None:
        with self._lock:
            self._db.close()

    def create(
        self, job_id: str, kind: str, request: dict[str, Any], retry_parent: str | None = None
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO jobs(id,kind,request_json,status,created_at,retry_parent) VALUES(?,?,?,?,?,?)",
                (job_id, kind, _json(request), "queued", utc_now(), retry_parent),
            )

    def update(self, job_id: str, **values: Any) -> None:
        allowed = {
            "status",
            "started_at",
            "finished_at",
            "progress_json",
            "result_json",
            "error_json",
            "worker_pid",
            "worker_start",
        }
        if set(values) - allowed:
            raise ValueError("invalid job field")
        with self._lock, self._db:
            self._db.execute(
                f"UPDATE jobs SET {','.join(f'{key}=?' for key in values)} WHERE id=?",
                (*values.values(), job_id),
            )

    def append_log(self, job_id: str, n: int, line: str) -> None:
        line = line[:4096]
        with self._lock, self._db:
            self._db.execute(
                "INSERT OR REPLACE INTO job_logs(job_id,n,ts,line) VALUES(?,?,?,?)",
                (job_id, n, utc_now(), line),
            )
            self._db.execute(
                "DELETE FROM job_logs WHERE job_id=? AND n NOT IN (SELECT n FROM job_logs WHERE job_id=? ORDER BY n DESC LIMIT 5000)",
                (job_id, job_id),
            )

    def latest_log_cursor(self, job_id: str) -> int:
        with self._lock:
            row = self._db.execute(
                "SELECT COALESCE(MAX(n),0) FROM job_logs WHERE job_id=?", (job_id,)
            ).fetchone()
            return int(row[0])

    def item(
        self, job_id: str, key: str, identity: dict[str, Any], state: str, result: Any = None
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO job_items(job_id,item_key,identity_json,state,result_json,completed_at) VALUES(?,?,?,?,?,?) "
                "ON CONFLICT(job_id,item_key) DO UPDATE SET state=excluded.state,result_json=excluded.result_json,completed_at=excluded.completed_at",
                (
                    job_id,
                    key,
                    _json(identity),
                    state,
                    _json(result) if result is not None else None,
                    utc_now() if state in TERMINAL | {"succeeded"} else None,
                ),
            )

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            return _decode_job(row) if row else None

    def logs_after(
        self, job_id: str, after: int, limit: int = 200
    ) -> tuple[list[dict[str, Any]], int, bool]:
        with self._lock:
            first = self._db.execute(
                "SELECT MIN(n) FROM job_logs WHERE job_id=?", (job_id,)
            ).fetchone()[0]
            rows = self._db.execute(
                "SELECT n,ts,line FROM job_logs WHERE job_id=? AND n>? ORDER BY n LIMIT ?",
                (job_id, after, min(limit, 200)),
            ).fetchall()
            cursor = int(rows[-1]["n"]) if rows else after
            return (
                [dict(row) for row in rows],
                cursor,
                bool(first is not None and after < first - 1),
            )

    def list_jobs(
        self, offset: int = 0, limit: int = 50
    ) -> tuple[dict[str, Any] | None, list[dict[str, Any]], int]:
        with self._lock:
            active_row = self._db.execute(
                "SELECT * FROM jobs WHERE status IN ('queued','running','stopping') ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
            total = int(
                self._db.execute(
                    "SELECT COUNT(*) FROM jobs WHERE status IN ('succeeded','failed','cancelled','interrupted')"
                ).fetchone()[0]
            )
            rows = self._db.execute(
                "SELECT * FROM jobs WHERE status IN ('succeeded','failed','cancelled','interrupted') ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (min(limit, 100), max(offset, 0)),
            ).fetchall()
            return (
                _decode_job(active_row) if active_row else None,
                [_decode_job(row) for row in rows],
                total,
            )

    def completed_items(self, job_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM job_items WHERE job_id=? AND state='succeeded'", (job_id,)
            ).fetchall()
            return [
                {
                    **dict(row),
                    "identity": json.loads(row["identity_json"]),
                    "result": json.loads(row["result_json"]) if row["result_json"] else None,
                }
                for row in rows
            ]

    def recover(self) -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE jobs SET status='interrupted', finished_at=? WHERE status IN ('queued','running','stopping')",
                (utc_now(),),
            )

    def active_workers(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT id,worker_pid,worker_start FROM jobs WHERE status IN ('queued','running','stopping') AND worker_pid IS NOT NULL"
            ).fetchall()
            return [dict(row) for row in rows]

    def retain(self, count: int = 100) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM jobs WHERE status IN ('succeeded','failed','cancelled','interrupted') AND id NOT IN (SELECT id FROM jobs WHERE status IN ('succeeded','failed','cancelled','interrupted') ORDER BY created_at DESC LIMIT ?)",
                (count,),
            )

    def put_view(
        self,
        platform: str,
        slug: str,
        inputs: Any,
        plan: Any,
        revision: str,
        freshness: str,
        attempt: str,
        success: str | None,
        error: Any = None,
    ) -> None:
        with self._lock, self._db:
            self._db.execute(
                "INSERT INTO series_views VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(platform,slug) DO UPDATE SET inputs_json=excluded.inputs_json,plan_json=excluded.plan_json,revision=excluded.revision,freshness=excluded.freshness,last_attempt_at=excluded.last_attempt_at,last_success_at=excluded.last_success_at,error_json=excluded.error_json",
                (
                    platform,
                    slug,
                    _json(inputs),
                    _json(plan),
                    revision,
                    freshness,
                    attempt,
                    success,
                    _json(error) if error is not None else None,
                ),
            )

    def get_view(self, platform: str, slug: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM series_views WHERE platform=? AND slug=?", (platform, slug)
            ).fetchone()
            if row is None:
                return None
            return {
                "inputs": json.loads(row["inputs_json"]),
                "plan": json.loads(row["plan_json"]),
                "revision": row["revision"],
                "freshness": row["freshness"],
                "last_attempt_at": row["last_attempt_at"],
                "last_success_at": row["last_success_at"],
                "error": json.loads(row["error_json"]) if row["error_json"] else None,
            }

    def views(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(
                "SELECT platform,slug FROM series_views ORDER BY platform,slug"
            ).fetchall()
            return [
                {
                    "platform": row["platform"],
                    "slug": row["slug"],
                    **(self.get_view(row["platform"], row["slug"]) or {}),
                }
                for row in rows
            ]

    def record_view_attempt(self, platform: str, slug: str, error: Any) -> None:
        with self._lock, self._db:
            timestamp = utc_now()
            self._db.execute(
                "INSERT INTO series_views(platform,slug,inputs_json,plan_json,revision,freshness,last_attempt_at,last_success_at,error_json) "
                "VALUES(?,?, '{}','{}','', 'unavailable', ?, NULL, ?) "
                "ON CONFLICT(platform,slug) DO UPDATE SET "
                "freshness=CASE WHEN series_views.last_success_at IS NULL THEN 'unavailable' ELSE 'stale' END, "
                "last_attempt_at=excluded.last_attempt_at,error_json=excluded.error_json",
                (platform, slug, timestamp, _json(error)),
            )

    def invalidate_view(
        self, platform: str, slug: str, reason: str = "Configuration changed"
    ) -> None:
        self.record_view_attempt(platform, slug, {"code": "CONFIG_CHANGED", "message": reason})

    def invalidate_platform(self, platform: str, reason: str = "Configuration changed") -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE series_views SET freshness='stale',last_attempt_at=?,error_json=? WHERE platform=?",
                (utc_now(), _json({"code": "CONFIG_CHANGED", "message": reason}), platform),
            )

    def invalidate_all(self, reason: str = "Configuration changed") -> None:
        with self._lock, self._db:
            self._db.execute(
                "UPDATE series_views SET freshness='stale',last_attempt_at=?,error_json=?",
                (utc_now(), _json({"code": "CONFIG_CHANGED", "message": reason})),
            )

    def delete_view(self, platform: str, slug: str) -> None:
        with self._lock, self._db:
            self._db.execute(
                "DELETE FROM series_views WHERE platform=? AND slug=?", (platform, slug)
            )


def _json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False, default=str)


def _decode_job(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "kind": row["kind"],
        "request": json.loads(row["request_json"]),
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "progress": json.loads(row["progress_json"]) if row["progress_json"] else None,
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
        "error": json.loads(row["error_json"]) if row["error_json"] else None,
        "retry_parent": row["retry_parent"],
    }
