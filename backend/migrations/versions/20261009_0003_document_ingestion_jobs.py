"""Add leased document-ingestion jobs.

Revision ID: 20261009_0003
Revises: 20261009_0002
"""
from __future__ import annotations

from alembic import op


revision = "20261009_0003"
down_revision = "20261009_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE document_source_versions (
            source_version TEXT PRIMARY KEY,
            file_count INTEGER NOT NULL CHECK (file_count > 0),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_source_files (
            source_version TEXT NOT NULL REFERENCES document_source_versions(source_version)
                ON DELETE CASCADE,
            source_file TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            content BYTEA NOT NULL,
            PRIMARY KEY (source_version, source_file)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_ingestion_jobs (
            job_id TEXT PRIMARY KEY,
            job_type TEXT NOT NULL CHECK (job_type = 'document_reindex'),
            idempotency_key TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL DEFAULT 'queued'
                CHECK (status IN ('queued', 'running', 'succeeded', 'dead')),
            payload JSONB NOT NULL DEFAULT '{}'::jsonb,
            attempts INTEGER NOT NULL DEFAULT 0 CHECK (attempts >= 0),
            max_attempts INTEGER NOT NULL DEFAULT 3 CHECK (max_attempts > 0),
            locked_by TEXT,
            lease_expires_at TIMESTAMPTZ,
            last_error TEXT,
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            started_at TIMESTAMPTZ,
            completed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX document_ingestion_jobs_status_created_idx "
        "ON document_ingestion_jobs (status, created_at)"
    )
    op.execute(
        "CREATE INDEX document_ingestion_jobs_lease_idx "
        "ON document_ingestion_jobs (lease_expires_at) WHERE status = 'running'"
    )


def downgrade() -> None:
    op.execute("DROP TABLE document_ingestion_jobs")
    op.execute("DROP TABLE document_source_files")
    op.execute("DROP TABLE document_source_versions")
