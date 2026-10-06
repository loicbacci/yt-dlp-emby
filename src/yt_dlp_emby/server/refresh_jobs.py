"""Small durable store for web refresh-job state.

Refresh work itself is deliberately kept in the single FastAPI process: it
shares the manifest and runner maintenance locks. SQLite only records status
so clients can distinguish a failed/restarted job from an indefinitely running
one.
"""

from __future__ import annotations

import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class RefreshJobStore:
    def __init__(self, data_dir: Path, *, ttl_seconds: float, max_entries: int) -> None:
        self.path = data_dir / "cache" / "refresh-jobs.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = ttl_seconds
        self.max_entries = max_entries
        self._initialize()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=5.0)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA synchronous=FULL")
            yield connection
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode=WAL")
            connection.execute(
                """CREATE TABLE IF NOT EXISTS refresh_jobs (
                    job_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                )"""
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS refresh_jobs_created ON refresh_jobs(created_at)"
            )

    def recover_interrupted(self) -> None:
        """Mark jobs from a previous process as interrupted; never replay writes."""
        now = time.time()
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT job_id, payload FROM refresh_jobs WHERE status = 'running'"
            ).fetchall()
            for row in rows:
                payload = json.loads(row["payload"])
                payload["status"] = "error"
                payload["result"] = None
                payload["error"] = "server restarted before refresh completed; run refresh again"
                payload["updated_at"] = now
                connection.execute(
                    "UPDATE refresh_jobs SET status = 'error', payload = ?, updated_at = ? "
                    "WHERE job_id = ?",
                    (json.dumps(payload, separators=(",", ":")), now, row["job_id"]),
                )
            self._prune(connection, now)

    def create(self, job_id: str, items: list[dict[str, str]]) -> dict[str, Any]:
        now = time.time()
        payload: dict[str, Any] = {
            "job_id": job_id,
            "items": items,
            "status": "running",
            "result": None,
            "error": None,
            "progress": {"completed": 0, "total": 0, "current": None},
            "created_at": now,
            "updated_at": now,
        }
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO refresh_jobs(job_id, status, payload, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (job_id, "running", json.dumps(payload, separators=(",", ":")), now, now),
            )
            self._prune(connection, now)
        return payload

    def update(self, job_id: str, **values: Any) -> dict[str, Any] | None:
        now = time.time()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM refresh_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
            if row is None:
                return None
            payload = json.loads(row["payload"])
            payload.update(values)
            payload["updated_at"] = now
            connection.execute(
                "UPDATE refresh_jobs SET status = ?, payload = ?, updated_at = ? WHERE job_id = ?",
                (
                    str(payload["status"]),
                    json.dumps(payload, separators=(",", ":")),
                    now,
                    job_id,
                ),
            )
            self._prune(connection, now)
        return payload

    def get(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM refresh_jobs WHERE job_id = ?", (job_id,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def active(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT payload FROM refresh_jobs WHERE status = 'running' ORDER BY created_at"
            ).fetchall()
        return [json.loads(row["payload"]) for row in rows]

    def _prune(self, connection: sqlite3.Connection, now: float) -> None:
        connection.execute(
            "DELETE FROM refresh_jobs WHERE status != 'running' AND updated_at < ?",
            (now - self.ttl_seconds,),
        )
        connection.execute(
            """DELETE FROM refresh_jobs WHERE job_id IN (
                SELECT job_id FROM refresh_jobs WHERE status != 'running'
                ORDER BY created_at DESC LIMIT -1 OFFSET ?
            )""",
            (self.max_entries,),
        )
