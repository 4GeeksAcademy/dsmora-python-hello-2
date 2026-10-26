import hashlib
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def candidate_digest(
    owner_id: str, version: int, title: str, content: str
) -> str:
    canonical = json.dumps(
        {
            "operation": "save_trip_plan",
            "owner_id": owner_id,
            "version": version,
            "title": title,
            "content": content,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ApprovalRegistry:
    """SQLite index for durable approvals; LangGraph checkpoints remain authoritative."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.connection = sqlite3.connect(
            path, timeout=30, check_same_thread=False, isolation_level=None
        )
        os.chmod(path, 0o600)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=30000")
        self.lock = threading.RLock()
        with self.lock:
            self.connection.execute(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    thread_id TEXT PRIMARY KEY,
                    owner_id TEXT NOT NULL,
                    conversation_id TEXT NOT NULL,
                    job_id TEXT NOT NULL,
                    request_id TEXT NOT NULL UNIQUE,
                    operation_id TEXT NOT NULL UNIQUE,
                    status TEXT NOT NULL,
                    candidate TEXT NOT NULL,
                    digest TEXT NOT NULL,
                    decision TEXT,
                    result TEXT,
                    error TEXT,
                    updated_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            self.connection.execute(
                """
                UPDATE approvals
                SET status = CASE json_extract(decision, '$.action')
                    WHEN 'approve' THEN 'approved' ELSE 'denied' END
                WHERE status = 'resuming' AND decision IS NOT NULL
                """
            )

    def prepare(
        self,
        *,
        thread_id: str,
        owner_id: str,
        conversation_id: str,
        job_id: str,
        request_id: str,
        operation_id: str,
        candidate: dict[str, Any],
    ) -> None:
        with self.lock:
            self.connection.execute(
                """
                INSERT INTO approvals (
                    thread_id, owner_id, conversation_id, job_id, request_id,
                    operation_id, status, candidate, digest
                ) VALUES (?, ?, ?, ?, ?, ?, 'prepared', ?, ?)
                """,
                (
                    thread_id, owner_id, conversation_id, job_id, request_id,
                    operation_id, json.dumps(candidate, ensure_ascii=False), candidate["digest"],
                ),
            )

    def update(
        self,
        thread_id: str,
        status: str,
        *,
        result: Any = None,
        error: str | None = None,
    ) -> None:
        with self.lock:
            self.connection.execute(
                """
                UPDATE approvals
                SET status = ?, result = COALESCE(?, result), error = ?, updated_at = datetime('now')
                WHERE thread_id = ?
                """,
                (
                    status,
                    json.dumps(result, ensure_ascii=False) if result is not None else None,
                    error,
                    thread_id,
                ),
            )

    def record_decision(
        self,
        *,
        thread_id: str,
        owner_id: str,
        request_id: str,
        version: int,
        digest: str,
        action: str,
        actor_id: str,
    ) -> bool:
        decision = json.dumps(
            {
                "action": action,
                "actor_id": actor_id,
                "decided_at": datetime.now(timezone.utc).isoformat(),
            },
            ensure_ascii=False,
        )
        with self.lock:
            cursor = self.connection.execute(
                """
                UPDATE approvals
                SET status = ?, decision = ?, updated_at = datetime('now')
                WHERE thread_id = ? AND owner_id = ? AND request_id = ?
                  AND status = 'awaiting_approval' AND digest = ?
                  AND json_extract(candidate, '$.version') = ?
                """,
                (
                    "approved" if action == "approve" else "denied",
                    decision,
                    thread_id,
                    owner_id,
                    request_id,
                    digest,
                    version,
                ),
            )
            return cursor.rowcount == 1

    def claim_resume(self, thread_id: str) -> dict[str, Any] | None:
        with self.lock:
            self.connection.execute("BEGIN IMMEDIATE")
            try:
                row = self.connection.execute(
                    """
                    SELECT owner_id, conversation_id, job_id, request_id, operation_id,
                           status, candidate, digest, decision, result, error
                    FROM approvals WHERE thread_id = ?
                    """,
                    (thread_id,),
                ).fetchone()
                if row is None or row[5] not in {"approved", "denied"}:
                    self.connection.execute("COMMIT")
                    return None
                self.connection.execute(
                    "UPDATE approvals SET status = 'resuming', updated_at = datetime('now') WHERE thread_id = ?",
                    (thread_id,),
                )
                self.connection.execute("COMMIT")
                return self._decode(thread_id, row)
            except Exception:
                self.connection.execute("ROLLBACK")
                raise

    def get(self, thread_id: str) -> dict[str, Any] | None:
        with self.lock:
            row = self.connection.execute(
                """
                SELECT owner_id, conversation_id, job_id, request_id, operation_id,
                       status, candidate, digest, decision, result, error
                FROM approvals WHERE thread_id = ?
                """,
                (thread_id,),
            ).fetchone()
        return self._decode(thread_id, row) if row is not None else None

    def release_resume(self, thread_id: str) -> None:
        with self.lock:
            self.connection.execute(
                """
                UPDATE approvals
                SET status = CASE json_extract(decision, '$.action')
                    WHEN 'approve' THEN 'approved' ELSE 'denied' END,
                    updated_at = datetime('now')
                WHERE thread_id = ? AND status = 'resuming' AND decision IS NOT NULL
                """,
                (thread_id,),
            )

    def pending_for_owner(self, owner_id: str) -> list[dict[str, Any]]:
        with self.lock:
            rows = self.connection.execute(
                """
                SELECT thread_id, owner_id, conversation_id, job_id, request_id, operation_id,
                       status, candidate, digest, decision, result, error
                FROM approvals WHERE owner_id = ? AND status = 'awaiting_approval'
                ORDER BY updated_at DESC
                """,
                (owner_id,),
            ).fetchall()
        return [self._decode(row[0], row[1:]) for row in rows]

    def _decode(self, thread_id: str, row: tuple[Any, ...]) -> dict[str, Any]:
        return {
            "thread_id": thread_id,
            "owner_id": row[0],
            "conversation_id": row[1],
            "job_id": row[2],
            "request_id": row[3],
            "operation_id": row[4],
            "status": row[5],
            "candidate": json.loads(row[6]),
            "digest": row[7],
            "decision": json.loads(row[8]) if row[8] else None,
            "result": json.loads(row[9]) if row[9] else None,
            "error": row[10],
        }

    def close(self) -> None:
        with self.lock:
            self.connection.close()
