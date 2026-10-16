from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from .document_parser import load_document_chunks


def build_ingestion_artifacts(documents_dir: Path, output_dir: Path) -> dict[str, object]:
    """Parse the corpus and persist a reviewable chunk manifest for indexing jobs."""
    chunks, searchable_texts = load_document_chunks(documents_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    chunks_path = output_dir / "chunks.jsonl"
    with chunks_path.open("w", encoding="utf-8") as handle:
        for chunk, searchable_text in zip(chunks, searchable_texts):
            handle.write(
                json.dumps(
                    {
                        "chunk_id": chunk.chunk_id,
                        "text": chunk.text,
                        "searchable_text": searchable_text,
                        "metadata": chunk.metadata.model_dump(mode="json"),
                        "tokens": sorted(chunk.tokens),
                        "source_location": chunk.source_location,
                        "section": chunk.section,
                        "token_count": chunk.token_count,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    manifest = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "documents_dir": str(documents_dir),
        "chunk_count": len(chunks),
        "document_count": len({chunk.metadata.document_id for chunk in chunks}),
        "chunks_file": str(chunks_path),
        "content_hashes": {
            chunk.metadata.document_id: chunk.metadata.content_hash
            for chunk in chunks
            if chunk.metadata.content_hash
        },
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    return manifest
