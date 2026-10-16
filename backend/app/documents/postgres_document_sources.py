from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import psycopg


SUPPORTED_DOCUMENT_SUFFIXES = {".txt", ".md", ".markdown", ".pdf", ".docx"}


class PostgresDocumentSourceStore:
    def __init__(self, database_url: str) -> None:
        self.database_url = database_url

    def upload_directory(self, documents_dir: Path) -> str:
        files = tuple(
            path
            for path in sorted(documents_dir.iterdir())
            if path.is_file() and path.suffix.lower() in SUPPORTED_DOCUMENT_SUFFIXES
        )
        if not files:
            raise ValueError(f"No supported documents found in {documents_dir}.")
        rows: list[tuple[str, str, bytes]] = []
        digest = sha256()
        for path in files:
            content = path.read_bytes()
            content_hash = sha256(content).hexdigest()
            digest.update(path.name.encode("utf-8"))
            digest.update(content_hash.encode("ascii"))
            rows.append((path.name, content_hash, content))
        source_version = digest.hexdigest()[:24]

        with psycopg.connect(self.database_url) as connection:
            connection.execute(
                """
                INSERT INTO document_source_versions (source_version, file_count)
                VALUES (%s, %s)
                ON CONFLICT (source_version) DO NOTHING
                """,
                (source_version, len(rows)),
            )
            with connection.cursor() as cursor:
                cursor.executemany(
                    """
                    INSERT INTO document_source_files (
                        source_version, source_file, content_hash, content
                    ) VALUES (%s, %s, %s, %s)
                    ON CONFLICT (source_version, source_file) DO NOTHING
                    """,
                    [
                        (source_version, source_file, content_hash, content)
                        for source_file, content_hash, content in rows
                    ],
                )
            stored_count = connection.execute(
                "SELECT COUNT(*) FROM document_source_files WHERE source_version = %s",
                (source_version,),
            ).fetchone()[0]
            if stored_count != len(rows):
                raise RuntimeError("Stored document source does not match its manifest.")
        return source_version

    def load(self, source_version: str) -> tuple[tuple[str, bytes], ...]:
        with psycopg.connect(self.database_url) as connection:
            rows = connection.execute(
                """
                SELECT source_file, content
                FROM document_source_files
                WHERE source_version = %s
                ORDER BY source_file
                """,
                (source_version,),
            ).fetchall()
        sources = tuple((str(source_file), bytes(content)) for source_file, content in rows)
        if not sources:
            raise ValueError(f"Document source version {source_version} was not found.")
        if any(Path(source_file).name != source_file for source_file, _ in sources):
            raise ValueError("Stored document source contains an unsafe filename.")
        return sources
