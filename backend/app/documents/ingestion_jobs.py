from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb


@dataclass(frozen=True)
class DocumentIngestionJob:
    job_id: str
    idempotency_key: str
    status: str
    payload: dict[str, Any]
    attempts: int
    max_attempts: int
    locked_by: str | None
    lease_expires_at: datetime | None
    last_error: str | None


class PostgresDocumentJobQueue:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def enqueue(
        self,
        idempotency_key: str,
        payload: dict[str, Any],
        *,
        max_attempts: int = 3,
    ) -> DocumentIngestionJob:
        if not idempotency_key.strip():
            raise ValueError("idempotency_key cannot be empty.")
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        with self._connection() as connection:
            row = connection.execute(
                """
                INSERT INTO document_ingestion_jobs (
                    job_id, job_type, idempotency_key, payload, max_attempts
                ) VALUES (%s, 'document_reindex', %s, %s, %s)
                ON CONFLICT (idempotency_key) DO UPDATE SET
                    idempotency_key = EXCLUDED.idempotency_key
                RETURNING *
                """,
                (str(uuid4()), idempotency_key, Jsonb(payload), max_attempts),
            ).fetchone()
        return _job_from_row(row)

    def claim(
        self,
        worker_id: str,
        *,
        lease_seconds: int = 300,
        idempotency_key: str | None = None,
    ) -> DocumentIngestionJob | None:
        if not worker_id.strip():
            raise ValueError("worker_id cannot be empty.")
        if lease_seconds < 1:
            raise ValueError("lease_seconds must be at least 1.")
        with self._connection() as connection:
            connection.execute(
                """
                UPDATE document_ingestion_jobs
                SET status = 'dead', locked_by = NULL,
                    lease_expires_at = NULL,
                    last_error = COALESCE(last_error, 'Worker lease expired on final attempt.'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE status = 'running'
                  AND lease_expires_at < CURRENT_TIMESTAMP
                  AND attempts >= max_attempts
                """
            )
            row = connection.execute(
                """
                WITH candidate AS (
                    SELECT job_id
                    FROM document_ingestion_jobs
                    WHERE attempts < max_attempts
                      AND (%s::text IS NULL OR idempotency_key = %s)
                      AND (
                          status = 'queued'
                          OR (status = 'running' AND lease_expires_at < CURRENT_TIMESTAMP)
                      )
                    ORDER BY created_at, job_id
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE document_ingestion_jobs AS jobs
                SET status = 'running',
                    attempts = jobs.attempts + 1,
                    locked_by = %s,
                    lease_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                    started_at = COALESCE(jobs.started_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                FROM candidate
                WHERE jobs.job_id = candidate.job_id
                RETURNING jobs.*
                """,
                (idempotency_key, idempotency_key, worker_id, lease_seconds),
            ).fetchone()
        return _job_from_row(row) if row else None

    def heartbeat(
        self,
        job_id: str,
        worker_id: str,
        *,
        lease_seconds: int = 300,
    ) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE document_ingestion_jobs
                SET lease_expires_at = CURRENT_TIMESTAMP + (%s * INTERVAL '1 second'),
                    updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s AND status = 'running' AND locked_by = %s
                RETURNING job_id
                """,
                (lease_seconds, job_id, worker_id),
            ).fetchone()
        return row is not None

    def complete(self, job_id: str, worker_id: str) -> bool:
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE document_ingestion_jobs
                SET status = 'succeeded', completed_at = CURRENT_TIMESTAMP,
                    lease_expires_at = NULL, locked_by = NULL,
                    last_error = NULL, updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s AND status = 'running' AND locked_by = %s
                RETURNING job_id
                """,
                (job_id, worker_id),
            ).fetchone()
        return row is not None

    def fail(self, job_id: str, worker_id: str, error: str) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                UPDATE document_ingestion_jobs
                SET status = CASE
                        WHEN attempts >= max_attempts THEN 'dead'
                        ELSE 'queued'
                    END,
                    lease_expires_at = NULL, locked_by = NULL,
                    last_error = LEFT(%s, 2000), updated_at = CURRENT_TIMESTAMP
                WHERE job_id = %s AND status = 'running' AND locked_by = %s
                RETURNING status
                """,
                (error, job_id, worker_id),
            ).fetchone()
        return str(row["status"]) if row else None

    def get(self, job_id: str) -> DocumentIngestionJob | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM document_ingestion_jobs WHERE job_id = %s",
                (job_id,),
            ).fetchone()
        return _job_from_row(row) if row else None

    def _connection(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)


def _job_from_row(row: dict[str, Any]) -> DocumentIngestionJob:
    return DocumentIngestionJob(
        job_id=str(row["job_id"]),
        idempotency_key=str(row["idempotency_key"]),
        status=str(row["status"]),
        payload=dict(row["payload"]),
        attempts=int(row["attempts"]),
        max_attempts=int(row["max_attempts"]),
        locked_by=row["locked_by"],
        lease_expires_at=row["lease_expires_at"],
        last_error=row["last_error"],
    )
