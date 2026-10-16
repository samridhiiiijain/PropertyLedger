from __future__ import annotations

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384


class DocumentEmbeddingModel:
    def __init__(self) -> None:
        self.model = SentenceTransformer(
            EMBEDDING_MODEL_NAME,
            local_files_only=True,
        )

    def encode(self, texts: tuple[str, ...]) -> np.ndarray:
        embeddings = self.model.encode(
            list(texts),
            convert_to_numpy=True,
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        values = np.asarray(embeddings, dtype=np.float32)
        if values.ndim != 2 or values.shape[1] != EMBEDDING_DIMENSION:
            raise RuntimeError(
                f"Embedding model returned dimension {values.shape[1] if values.ndim == 2 else 'unknown'}; "
                f"expected {EMBEDDING_DIMENSION}."
            )
        return values


class DocumentVectorIndex:
    def __init__(
        self,
        searchable_texts: tuple[str, ...],
        embedding_model: DocumentEmbeddingModel | None = None,
    ) -> None:
        self.embedding_model = embedding_model or DocumentEmbeddingModel()
        embeddings = self.embedding_model.encode(searchable_texts)
        self.index = faiss.IndexFlatIP(embeddings.shape[1])
        self.index.add(embeddings)

    def search(self, question: str, candidate_count: int) -> tuple[np.ndarray, np.ndarray]:
        return self.index.search(self.embedding_model.encode((question,)), candidate_count)
