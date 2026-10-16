from __future__ import annotations

from hashlib import sha256
from typing import Any

import numpy as np
import psycopg
from psycopg.rows import dict_row

from ..models import DocumentMetadata
from .document_query import tokens
from .document_types import DocumentChunk, QueryIdentifiers, RetrievedChunk
from .document_vector_index import (
    EMBEDDING_DIMENSION,
    EMBEDDING_MODEL_NAME,
    DocumentEmbeddingModel,
)


RRF_CONSTANT = 60


class PostgresDocumentSearchStore:
    def __init__(
        self,
        database_url: str,
        embedding_model: DocumentEmbeddingModel | None = None,
    ) -> None:
        self.database_url = database_url
        self.embedding_model = embedding_model or DocumentEmbeddingModel()

    @property
    def index_version(self) -> str | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT active_version FROM document_index_state WHERE singleton = TRUE"
            ).fetchone()
        return str(row["active_version"]) if row and row["active_version"] else None

    def readiness(self) -> dict[str, object]:
        try:
            with self._connection() as connection:
                extension = connection.execute(
                    "SELECT 1 FROM pg_extension WHERE extname = 'vector'"
                ).fetchone()
                version = connection.execute(
                    """
                    SELECT v.corpus_version, v.embedding_model_id,
                           v.embedding_dimension, COUNT(c.chunk_id) AS chunks
                    FROM document_index_state s
                    JOIN document_corpus_versions v
                      ON v.corpus_version = s.active_version
                    LEFT JOIN document_chunks c
                      ON c.corpus_version = v.corpus_version
                    WHERE s.singleton = TRUE
                    GROUP BY v.corpus_version, v.embedding_model_id,
                             v.embedding_dimension
                    """
                ).fetchone()
        except Exception as exc:
            return {
                "status": "unavailable",
                "backend": "postgres",
                "error_type": type(exc).__name__,
            }
        if not extension or not version:
            return {
                "status": "unavailable",
                "backend": "postgres",
                "index_version": None,
            }
        compatible = (
            version["embedding_model_id"] == EMBEDDING_MODEL_NAME
            and version["embedding_dimension"] == EMBEDDING_DIMENSION
        )
        return {
            "status": "ready" if compatible else "incompatible",
            "backend": "postgres",
            "index_version": str(version["corpus_version"]),
            "embedding_model_id": str(version["embedding_model_id"]),
            "embedding_dimension": int(version["embedding_dimension"]),
            "chunks": int(version["chunks"]),
        }

    def all_chunks(self) -> tuple[DocumentChunk, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT c.*
                FROM document_chunks c
                JOIN document_index_state s
                  ON s.active_version = c.corpus_version
                WHERE s.singleton = TRUE
                ORDER BY c.chunk_id
                """
            ).fetchall()
        return tuple(_chunk_from_row(row) for row in rows)

    def document_by_id(self, document_id: str) -> DocumentChunk | None:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT c.*
                FROM document_chunks c
                JOIN document_index_state s
                  ON s.active_version = c.corpus_version
                WHERE s.singleton = TRUE AND c.document_id = %(document_id)s
                ORDER BY c.chunk_id
                LIMIT 1
                """,
                {"document_id": document_id},
            ).fetchone()
        return _chunk_from_row(row) if row else None

    def search(
        self,
        question: str,
        *,
        identifiers: QueryIdentifiers,
        project_id: str | None,
        candidate_count: int,
        rerank_count: int,
        result_limit: int,
    ) -> tuple[RetrievedChunk, ...]:
        del rerank_count
        embedding = self.embedding_model.encode((question,))[0]
        scope_sql, parameters = _scope_filter(identifiers, project_id)
        parameters.update(
            {
                "question": question,
                "embedding": _vector_literal(embedding),
                "candidate_count": candidate_count,
                "result_limit": result_limit,
                "rrf_constant": RRF_CONSTANT,
            }
        )
        sql = f"""
            WITH active_chunks AS (
                SELECT c.*
                FROM document_chunks c
                JOIN document_index_state s
                  ON s.active_version = c.corpus_version
                WHERE s.singleton = TRUE{scope_sql}
            ),
            vector_candidates AS (
                SELECT chunk_id,
                       ROW_NUMBER() OVER (
                           ORDER BY embedding <=> %(embedding)s::vector
                       ) AS rank
                FROM active_chunks
                ORDER BY embedding <=> %(embedding)s::vector
                LIMIT %(candidate_count)s
            ),
            text_candidates AS (
                SELECT chunk_id,
                       ROW_NUMBER() OVER (
                           ORDER BY ts_rank_cd(
                               search_vector,
                               websearch_to_tsquery('english', %(question)s)
                           ) DESC
                       ) AS rank
                FROM active_chunks
                WHERE search_vector @@ websearch_to_tsquery('english', %(question)s)
                ORDER BY ts_rank_cd(
                    search_vector,
                    websearch_to_tsquery('english', %(question)s)
                ) DESC
                LIMIT %(candidate_count)s
            ),
            fused AS (
                SELECT chunk_id,
                       SUM(1.0 / (%(rrf_constant)s + rank)) AS score
                FROM (
                    SELECT chunk_id, rank FROM vector_candidates
                    UNION ALL
                    SELECT chunk_id, rank FROM text_candidates
                ) candidates
                GROUP BY chunk_id
            )
            SELECT c.*, fused.score
            FROM fused
            JOIN active_chunks c ON c.chunk_id = fused.chunk_id
            ORDER BY fused.score DESC, c.chunk_id
            LIMIT %(result_limit)s
        """
        with self._connection() as connection:
            rows = connection.execute(sql, parameters).fetchall()
        return tuple(
            RetrievedChunk(
                chunk=_chunk_from_row(row),
                score=float(row["score"]),
                retrieval_method="postgres_hybrid",
                rank=index,
            )
            for index, row in enumerate(rows, start=1)
        )

    def close(self) -> None:
        return None

    def _connection(self):
        return psycopg.connect(self.database_url, row_factory=dict_row)


class PostgresDocumentIndexer:
    def __init__(
        self,
        database_url: str,
        embedding_model: DocumentEmbeddingModel | None = None,
    ) -> None:
        self.database_url = database_url
        self.embedding_model = embedding_model or DocumentEmbeddingModel()

    def build_and_activate(
        self,
        chunks: tuple[DocumentChunk, ...],
        searchable_texts: tuple[str, ...],
    ) -> str:
        if len(chunks) != len(searchable_texts):
            raise ValueError("Every document chunk must have one searchable text.")
        if not chunks:
            raise ValueError("Cannot activate an empty document corpus.")
        corpus_version = _corpus_version(chunks)
        embeddings = self.embedding_model.encode(searchable_texts)
        rows = [
            _index_row(corpus_version, chunk, searchable_text, embedding)
            for chunk, searchable_text, embedding in zip(
                chunks,
                searchable_texts,
                embeddings,
                strict=True,
            )
        ]
        with psycopg.connect(self.database_url) as connection:
            with connection.transaction():
                connection.execute(
                    """
                    INSERT INTO document_corpus_versions (
                        corpus_version, embedding_model_id,
                        embedding_dimension, status
                    ) VALUES (%s, %s, %s, 'building')
                    ON CONFLICT (corpus_version) DO UPDATE SET
                        embedding_model_id = EXCLUDED.embedding_model_id,
                        embedding_dimension = EXCLUDED.embedding_dimension,
                        status = 'building'
                    """,
                    (corpus_version, EMBEDDING_MODEL_NAME, EMBEDDING_DIMENSION),
                )
                connection.execute(
                    "DELETE FROM document_chunks WHERE corpus_version = %s",
                    (corpus_version,),
                )
                with connection.cursor() as cursor:
                    cursor.executemany(
                        """
                        INSERT INTO document_chunks (
                            corpus_version, chunk_id, document_id, document_type,
                            document_date, source_file, property_id, project_id,
                            vendor_id, invoice_id, po_id, cost_code, content_hash,
                            source_location, section, token_count, chunk_text,
                            searchable_text, embedding
                        ) VALUES (
                            %(corpus_version)s, %(chunk_id)s, %(document_id)s,
                            %(document_type)s, %(document_date)s, %(source_file)s,
                            %(property_id)s, %(project_id)s, %(vendor_id)s,
                            %(invoice_id)s, %(po_id)s, %(cost_code)s,
                            %(content_hash)s, %(source_location)s, %(section)s,
                            %(token_count)s, %(chunk_text)s, %(searchable_text)s,
                            %(embedding)s::vector
                        )
                        """,
                        rows,
                    )
                stored_count = connection.execute(
                    "SELECT COUNT(*) FROM document_chunks WHERE corpus_version = %s",
                    (corpus_version,),
                ).fetchone()[0]
                if stored_count != len(chunks):
                    raise RuntimeError("Document corpus row-count validation failed.")
                connection.execute(
                    "UPDATE document_corpus_versions SET status = 'ready' "
                    "WHERE status = 'active' AND corpus_version <> %s",
                    (corpus_version,),
                )
                connection.execute(
                    "UPDATE document_corpus_versions SET status = 'active', "
                    "activated_at = CURRENT_TIMESTAMP WHERE corpus_version = %s",
                    (corpus_version,),
                )
                connection.execute(
                    """
                    INSERT INTO document_index_state (singleton, active_version)
                    VALUES (TRUE, %s)
                    ON CONFLICT (singleton) DO UPDATE SET
                        active_version = EXCLUDED.active_version,
                        updated_at = CURRENT_TIMESTAMP
                    """,
                    (corpus_version,),
                )
        return corpus_version


def _scope_filter(
    identifiers: QueryIdentifiers,
    project_id: str | None,
) -> tuple[str, dict[str, Any]]:
    clauses: list[str] = []
    parameters: dict[str, Any] = {}
    scopes = {
        "project_id": identifiers.project_id or project_id,
        "property_id": identifiers.property_id,
        "vendor_id": identifiers.vendor_id,
        "invoice_id": identifiers.invoice_id,
        "po_id": identifiers.po_id,
        "cost_code": identifiers.cost_code,
    }
    for parameter, value in scopes.items():
        if value is None:
            continue
        clauses.append(
            f" AND (c.{parameter} IS NULL OR c.{parameter} = %({parameter})s)"
        )
        parameters[parameter] = value
    return "".join(clauses), parameters


def _chunk_from_row(row: dict[str, Any]) -> DocumentChunk:
    metadata = DocumentMetadata(
        document_id=row["document_id"],
        document_type=row["document_type"],
        document_date=row.get("document_date"),
        source_file=row["source_file"],
        property_id=row.get("property_id"),
        project_id=row.get("project_id"),
        vendor_id=row.get("vendor_id"),
        invoice_id=row.get("invoice_id"),
        po_id=row.get("po_id"),
        cost_code=row.get("cost_code"),
        content_hash=row.get("content_hash"),
    )
    return DocumentChunk(
        chunk_id=row["chunk_id"],
        text=row["chunk_text"],
        metadata=metadata,
        tokens=frozenset(tokens(row["searchable_text"])),
        source_location=row.get("source_location"),
        section=row.get("section"),
        token_count=int(row["token_count"]),
    )


def _corpus_version(chunks: tuple[DocumentChunk, ...]) -> str:
    digest = sha256()
    digest.update(EMBEDDING_MODEL_NAME.encode("utf-8"))
    digest.update(str(EMBEDDING_DIMENSION).encode("ascii"))
    for chunk in chunks:
        digest.update(chunk.chunk_id.encode("utf-8"))
        digest.update((chunk.metadata.content_hash or "").encode("ascii"))
        digest.update(chunk.text.encode("utf-8"))
    return digest.hexdigest()[:24]


def _index_row(
    corpus_version: str,
    chunk: DocumentChunk,
    searchable_text: str,
    embedding: np.ndarray,
) -> dict[str, Any]:
    metadata = chunk.metadata
    return {
        "corpus_version": corpus_version,
        "chunk_id": chunk.chunk_id,
        "document_id": metadata.document_id,
        "document_type": metadata.document_type,
        "document_date": metadata.document_date,
        "source_file": metadata.source_file,
        "property_id": metadata.property_id,
        "project_id": metadata.project_id,
        "vendor_id": metadata.vendor_id,
        "invoice_id": metadata.invoice_id,
        "po_id": metadata.po_id,
        "cost_code": metadata.cost_code,
        "content_hash": metadata.content_hash,
        "source_location": chunk.source_location,
        "section": chunk.section,
        "token_count": chunk.token_count,
        "chunk_text": chunk.text,
        "searchable_text": searchable_text,
        "embedding": _vector_literal(embedding),
    }


def _vector_literal(embedding: np.ndarray) -> str:
    if embedding.shape != (EMBEDDING_DIMENSION,):
        raise ValueError(f"Expected an embedding with {EMBEDDING_DIMENSION} dimensions.")
    return "[" + ",".join(f"{float(value):.8g}" for value in embedding) + "]"
