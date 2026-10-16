from __future__ import annotations

from datetime import date
import hashlib
from io import BytesIO
from pathlib import Path
import re

from .document_query import tokens
from .document_types import DocumentChunk
from ..models import DocumentMetadata


DOCUMENTS_DIR = Path(__file__).resolve().parents[3] / "data" / "documents"

METADATA_KEYS = {
    "Document ID": "document_id",
    "Document Type": "document_type",
    "Document Date": "document_date",
    "Property ID": "property_id",
    "Project ID": "project_id",
    "Vendor ID": "vendor_id",
    "Invoice ID": "invoice_id",
    "PO ID": "po_id",
    "Cost Code": "cost_code",
}


def load_document_chunks(
    documents_dir: Path = DOCUMENTS_DIR,
) -> tuple[tuple[DocumentChunk, ...], tuple[str, ...]]:
    supported_suffixes = {".txt", ".md", ".markdown", ".pdf", ".docx"}
    sources = tuple(
        (path.name, path.read_bytes())
        for path in sorted(documents_dir.iterdir())
        if path.is_file() and path.suffix.lower() in supported_suffixes
    )
    return load_document_chunks_from_sources(sources)


def load_document_chunks_from_sources(
    sources: tuple[tuple[str, bytes], ...],
) -> tuple[tuple[DocumentChunk, ...], tuple[str, ...]]:
    chunks: list[DocumentChunk] = []
    searchable_texts: list[str] = []
    for source_file, content in sources:
        metadata, body = parse_document_content(source_file, content)
        for index, (chunk_text, location, section) in enumerate(chunk_text_body(metadata, body), start=1):
            searchable_text = searchable_document_text(metadata, chunk_text)
            chunks.append(
                DocumentChunk(
                    chunk_id=f"{metadata.document_id}-C{index:03d}",
                    text=chunk_text,
                    metadata=metadata,
                    tokens=frozenset(tokens(searchable_text)),
                    source_location=location,
                    section=section,
                    token_count=len(tokens(chunk_text)),
                )
            )
            searchable_texts.append(searchable_text)

    return tuple(chunks), tuple(searchable_texts)


def parse_document(path: Path) -> tuple[DocumentMetadata, str]:
    return parse_document_content(path.name, path.read_bytes())


def parse_document_content(
    source_file: str,
    content: bytes,
) -> tuple[DocumentMetadata, str]:
    metadata_lines: dict[str, str] = {}
    body_lines: list[str] = []
    in_body = False

    raw_text = extract_document_content(source_file, content)
    for line in raw_text.splitlines():
        if not in_body and not line.strip():
            in_body = True
            continue

        if not in_body and ":" in line:
            raw_key, raw_value = line.split(":", 1)
            key = raw_key.strip()
            if key in METADATA_KEYS:
                metadata_lines[key] = raw_value.strip()
                continue

        body_lines.append(line)

    document_date = None
    if metadata_lines.get("Document Date"):
        document_date = date.fromisoformat(metadata_lines["Document Date"])

    metadata = DocumentMetadata(
        document_id=(
            metadata_value(metadata_lines, "Document ID")
            or Path(source_file).stem.upper()
        ),
        document_type=metadata_lines.get("Document Type", "Document"),
        document_date=document_date,
        source_file=source_file,
        property_id=metadata_value(metadata_lines, "Property ID"),
        project_id=metadata_value(metadata_lines, "Project ID"),
        vendor_id=metadata_value(metadata_lines, "Vendor ID"),
        invoice_id=metadata_value(metadata_lines, "Invoice ID"),
        po_id=metadata_value(metadata_lines, "PO ID"),
        cost_code=metadata_value(metadata_lines, "Cost Code"),
        content_hash=hashlib.sha256(content).hexdigest(),
    )
    return metadata, "\n".join(line for line in body_lines if line.strip())


def extract_document_text(path: Path) -> str:
    return extract_document_content(path.name, path.read_bytes())


def extract_document_content(source_file: str, content: bytes) -> str:
    suffix = Path(source_file).suffix.lower()
    if suffix in {".txt", ".md", ".markdown"}:
        return content.decode("utf-8")
    if suffix == ".pdf":
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF ingestion requires the pypdf dependency.") from exc
        reader = PdfReader(BytesIO(content))
        pages = []
        for page_number, page in enumerate(reader.pages, start=1):
            pages.append(f"Page {page_number}\n{page.extract_text() or ''}")
        return "\n\n".join(pages)
    if suffix == ".docx":
        try:
            from docx import Document
        except ImportError as exc:
            raise RuntimeError("DOCX ingestion requires the python-docx dependency.") from exc
        document = Document(BytesIO(content))
        return "\n\n".join(paragraph.text for paragraph in document.paragraphs)
    raise ValueError(f"Unsupported document format: {suffix}")


def metadata_value(lines: dict[str, str], key: str) -> str | None:
    value = lines.get(key)
    return value.strip().upper() if value else None


def chunk_text_body(
    metadata: DocumentMetadata,
    body: str,
    *,
    max_tokens: int = 180,
    overlap_tokens: int = 30,
) -> tuple[tuple[str, str, str | None], ...]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", body) if part.strip()]
    if not paragraphs:
        return ((body.strip(), "paragraph:1", None),)

    chunks: list[tuple[str, str, str | None]] = []
    current_tokens: list[str] = []
    current_parts: list[str] = []
    current_start = 1
    for paragraph_index, paragraph in enumerate(paragraphs, start=1):
        paragraph_tokens = list(tokens(paragraph))
        if not paragraph_tokens:
            continue
        if current_tokens and len(current_tokens) + len(paragraph_tokens) > max_tokens:
            chunks.append(("\n\n".join(current_parts), f"paragraph:{current_start}-{paragraph_index - 1}", None))
            overlap = current_tokens[-overlap_tokens:] if overlap_tokens else []
            current_tokens = list(overlap)
            current_parts = [" ".join(overlap)] if overlap else []
            current_start = paragraph_index
        if len(paragraph_tokens) > max_tokens:
            for start in range(0, len(paragraph_tokens), max_tokens - overlap_tokens):
                part_tokens = paragraph_tokens[start : start + max_tokens]
                if part_tokens:
                    chunks.append((" ".join(part_tokens), f"paragraph:{paragraph_index}:{start + 1}-{start + len(part_tokens)}", None))
            current_tokens = []
            current_parts = []
            current_start = paragraph_index + 1
            continue
        current_tokens.extend(paragraph_tokens)
        current_parts.append(paragraph)

    if current_parts:
        chunks.append(("\n\n".join(current_parts), f"paragraph:{current_start}-{len(paragraphs)}", None))
    return tuple(chunks) or ((body.strip() or metadata.document_id, "paragraph:1", None),)


def searchable_document_text(metadata: DocumentMetadata, chunk_text: str) -> str:
    return "\n".join(
        [
            metadata.document_id,
            metadata.document_type,
            metadata.project_id or "",
            metadata.property_id or "",
            metadata.vendor_id or "",
            metadata.invoice_id or "",
            metadata.po_id or "",
            metadata.cost_code or "",
            chunk_text,
        ]
    )
