"""Add the versioned PostgreSQL document search store.

Revision ID: 20261009_0002
Revises: 20261008_0001
"""
from __future__ import annotations

from alembic import op


revision = "20261009_0002"
down_revision = "20261008_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        CREATE TABLE document_corpus_versions (
            corpus_version TEXT PRIMARY KEY,
            embedding_model_id TEXT NOT NULL,
            embedding_dimension INTEGER NOT NULL CHECK (embedding_dimension > 0),
            status TEXT NOT NULL CHECK (status IN ('building', 'ready', 'active', 'failed')),
            created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
            activated_at TIMESTAMPTZ
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_chunks (
            corpus_version TEXT NOT NULL REFERENCES document_corpus_versions(corpus_version)
                ON DELETE CASCADE,
            chunk_id TEXT NOT NULL,
            document_id TEXT NOT NULL,
            document_type TEXT NOT NULL,
            document_date DATE,
            source_file TEXT NOT NULL,
            property_id TEXT,
            project_id TEXT,
            vendor_id TEXT,
            invoice_id TEXT,
            po_id TEXT,
            cost_code TEXT,
            content_hash TEXT,
            source_location TEXT,
            section TEXT,
            token_count INTEGER NOT NULL,
            chunk_text TEXT NOT NULL,
            searchable_text TEXT NOT NULL,
            embedding vector(384) NOT NULL,
            search_vector TSVECTOR GENERATED ALWAYS AS (
                to_tsvector('english', searchable_text)
            ) STORED,
            PRIMARY KEY (corpus_version, chunk_id)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE document_index_state (
            singleton BOOLEAN PRIMARY KEY DEFAULT TRUE CHECK (singleton),
            active_version TEXT NOT NULL REFERENCES document_corpus_versions(corpus_version),
            updated_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    op.execute(
        "CREATE INDEX document_corpus_status_idx ON document_corpus_versions (status)"
    )
    op.execute(
        "CREATE INDEX document_chunks_project_idx ON document_chunks (corpus_version, project_id)"
    )
    op.execute(
        "CREATE INDEX document_chunks_document_idx ON document_chunks (corpus_version, document_id)"
    )
    op.execute(
        "CREATE INDEX document_chunks_search_idx ON document_chunks USING GIN (search_vector)"
    )
    op.execute(
        "CREATE INDEX document_chunks_embedding_idx ON document_chunks "
        "USING hnsw (embedding vector_cosine_ops)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE document_index_state")
    op.execute("DROP TABLE document_chunks")
    op.execute("DROP TABLE document_corpus_versions")

