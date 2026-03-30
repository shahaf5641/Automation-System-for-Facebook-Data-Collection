from __future__ import annotations

import json
import logging
import os
from typing import Any

try:
    import psycopg
except ImportError:  # pragma: no cover
    psycopg = None

logger = logging.getLogger(__name__)


class BaseRunHistoryStore:
    backend_name = "disabled"

    def upsert_job(self, record: dict[str, Any]) -> None:
        raise NotImplementedError

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        raise NotImplementedError

    def list_jobs_for_client(self, client_id: str) -> list[dict[str, Any]]:
        raise NotImplementedError

    def cleanup_old_runs(self, older_than_ts: float) -> int:
        raise NotImplementedError

    def delete_job(self, job_id: str) -> bool:
        raise NotImplementedError

    def delete_jobs_for_client(self, client_id: str) -> int:
        raise NotImplementedError


class DisabledRunHistoryStore(BaseRunHistoryStore):
    def upsert_job(self, record: dict[str, Any]) -> None:
        return

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return None

    def list_jobs_for_client(self, client_id: str) -> list[dict[str, Any]]:
        return []

    def cleanup_old_runs(self, older_than_ts: float) -> int:
        return 0

    def delete_job(self, job_id: str) -> bool:
        return False

    def delete_jobs_for_client(self, client_id: str) -> int:
        return 0


class PostgresRunHistoryStore(BaseRunHistoryStore):
    backend_name = "postgres"

    def __init__(self, dsn: str) -> None:
        self.dsn = dsn
        self._ensure_schema()

    def _connect(self):
        return psycopg.connect(self.dsn)

    def _ensure_schema(self) -> None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS run_history (
                        job_id TEXT PRIMARY KEY,
                        owner_client_id TEXT NOT NULL,
                        search_word TEXT NOT NULL,
                        group_links_number INTEGER NOT NULL,
                        posts_from_each_group INTEGER NOT NULL,
                        status TEXT NOT NULL,
                        message TEXT NOT NULL,
                        output_file TEXT NOT NULL,
                        target_posts INTEGER NOT NULL,
                        captured_posts INTEGER NOT NULL,
                        progress_percent INTEGER NOT NULL,
                        progress_text TEXT NOT NULL,
                        queue_position INTEGER NOT NULL,
                        created_at DOUBLE PRECISION NOT NULL,
                        updated_at DOUBLE PRECISION NOT NULL,
                        finished_at DOUBLE PRECISION NOT NULL,
                        record_json JSONB NOT NULL
                    );
                    CREATE INDEX IF NOT EXISTS idx_run_history_owner_created
                    ON run_history (owner_client_id, created_at DESC);
                    """
                )
            conn.commit()

    def upsert_job(self, record: dict[str, Any]) -> None:
        settings = record.get("settings", {})
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO run_history (
                        job_id,
                        owner_client_id,
                        search_word,
                        group_links_number,
                        posts_from_each_group,
                        status,
                        message,
                        output_file,
                        target_posts,
                        captured_posts,
                        progress_percent,
                        progress_text,
                        queue_position,
                        created_at,
                        updated_at,
                        finished_at,
                        record_json
                    )
                    VALUES (
                        %(job_id)s,
                        %(owner_client_id)s,
                        %(search_word)s,
                        %(group_links_number)s,
                        %(posts_from_each_group)s,
                        %(status)s,
                        %(message)s,
                        %(output_file)s,
                        %(target_posts)s,
                        %(captured_posts)s,
                        %(progress_percent)s,
                        %(progress_text)s,
                        %(queue_position)s,
                        %(created_at)s,
                        %(updated_at)s,
                        %(finished_at)s,
                        %(record_json)s::jsonb
                    )
                    ON CONFLICT (job_id) DO UPDATE SET
                        owner_client_id = EXCLUDED.owner_client_id,
                        search_word = EXCLUDED.search_word,
                        group_links_number = EXCLUDED.group_links_number,
                        posts_from_each_group = EXCLUDED.posts_from_each_group,
                        status = EXCLUDED.status,
                        message = EXCLUDED.message,
                        output_file = EXCLUDED.output_file,
                        target_posts = EXCLUDED.target_posts,
                        captured_posts = EXCLUDED.captured_posts,
                        progress_percent = EXCLUDED.progress_percent,
                        progress_text = EXCLUDED.progress_text,
                        queue_position = EXCLUDED.queue_position,
                        created_at = EXCLUDED.created_at,
                        updated_at = EXCLUDED.updated_at,
                        finished_at = EXCLUDED.finished_at,
                        record_json = EXCLUDED.record_json::jsonb;
                    """,
                    {
                        "job_id": record["job_id"],
                        "owner_client_id": record["owner_client_id"],
                        "search_word": settings.get("search_word", ""),
                        "group_links_number": int(settings.get("group_links_number", 0) or 0),
                        "posts_from_each_group": int(settings.get("posts_from_each_group", 0) or 0),
                        "status": record.get("status", "queued"),
                        "message": record.get("message", ""),
                        "output_file": record.get("output_file", ""),
                        "target_posts": int(record.get("target_posts", 0) or 0),
                        "captured_posts": int(record.get("captured_posts", 0) or 0),
                        "progress_percent": int(record.get("progress_percent", 0) or 0),
                        "progress_text": record.get("progress_text", ""),
                        "queue_position": int(record.get("queue_position", 0) or 0),
                        "created_at": float(record.get("created_at", 0.0) or 0.0),
                        "updated_at": float(record.get("updated_at", 0.0) or 0.0),
                        "finished_at": float(record.get("finished_at", 0.0) or 0.0),
                        "record_json": json.dumps(record, ensure_ascii=True),
                    },
                )
            conn.commit()

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT record_json FROM run_history WHERE job_id = %s", (job_id,))
                row = cur.fetchone()
        if row is None:
            return None
        payload = row[0]
        return payload if isinstance(payload, dict) else json.loads(payload)

    def list_jobs_for_client(self, client_id: str) -> list[dict[str, Any]]:
        if not client_id:
            return []
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT
                        job_id,
                        owner_client_id,
                        search_word,
                        group_links_number,
                        posts_from_each_group,
                        status,
                        message,
                        output_file,
                        target_posts,
                        captured_posts,
                        progress_percent,
                        progress_text,
                        queue_position,
                        created_at,
                        updated_at,
                        finished_at
                    FROM run_history
                    WHERE owner_client_id = %s
                    ORDER BY created_at DESC, job_id DESC
                    """,
                    (client_id,),
                )
                rows = cur.fetchall()
        return [
            {
                "job_id": row[0],
                "owner_client_id": row[1],
                "search_word": row[2],
                "group_links_number": row[3],
                "posts_from_each_group": row[4],
                "status": row[5],
                "message": row[6],
                "output_file": row[7],
                "output_ready": bool(row[7] and os.path.exists(row[7])),
                "target_posts": row[8],
                "captured_posts": row[9],
                "progress_percent": row[10],
                "progress_text": row[11],
                "queue_position": row[12],
                "created_at": row[13],
                "updated_at": row[14],
                "finished_at": row[15],
            }
            for row in rows
        ]

    def cleanup_old_runs(self, older_than_ts: float) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    DELETE FROM run_history
                    WHERE status IN ('completed', 'failed', 'stopped')
                      AND COALESCE(NULLIF(finished_at, 0), updated_at) < %s
                    """,
                    (older_than_ts,),
                )
                removed = cur.rowcount or 0
            conn.commit()
        return removed

    def delete_job(self, job_id: str) -> bool:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM run_history WHERE job_id = %s", (job_id,))
                removed = cur.rowcount or 0
            conn.commit()
        return bool(removed)

    def delete_jobs_for_client(self, client_id: str) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("DELETE FROM run_history WHERE owner_client_id = %s", (client_id,))
                removed = cur.rowcount or 0
            conn.commit()
        return removed


def build_run_history_store() -> BaseRunHistoryStore:
    database_url = os.getenv("DATABASE_URL", "").strip()
    if not database_url:
        logger.info("PostgreSQL run history is not configured. History will stay in Redis/memory only.")
        return DisabledRunHistoryStore()

    if psycopg is None:
        logger.warning("DATABASE_URL is set but psycopg is not installed. PostgreSQL history is disabled.")
        return DisabledRunHistoryStore()

    try:
        store = PostgresRunHistoryStore(database_url)
        logger.info("Connected to PostgreSQL run history store.")
        return store
    except Exception as exc:  # pragma: no cover
        logger.warning("Could not initialize PostgreSQL run history store: %s", exc)
        return DisabledRunHistoryStore()
