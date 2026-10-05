import json
from pathlib import Path
from typing import Protocol

import faiss
import numpy as np

from src.config.settings import Settings
from src.models.schemas import Chunk, RetrievedChunk


class VectorStore(Protocol):
    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None: ...

    def search(
        self, query_vector: list[float], top_k: int, query_text: str | None = None
    ) -> list[RetrievedChunk]:
        """query_text enables hybrid (keyword + vector) search where the store supports it."""
        ...

    def delete_document(self, document_id: str) -> None: ...

    def list_documents(self) -> dict[str, str]: ...


class FaissVectorStore:
    """Cosine-similarity store persisted to disk as chunks.json + vectors.npy.

    The FAISS index is rebuilt from the saved vectors on load, which keeps deletes trivial.
    Fine for the small corpora this project targets; Azure AI Search replaces it in Phase 3.
    """

    def __init__(self, index_dir: Path):
        self._dir = index_dir
        self._chunks: list[Chunk] = []
        self._vectors = np.zeros((0, 0), dtype="float32")
        self._index: faiss.Index | None = None
        self._load()

    @property
    def _chunks_path(self) -> Path:
        return self._dir / "chunks.json"

    @property
    def _vectors_path(self) -> Path:
        return self._dir / "vectors.npy"

    def _load(self) -> None:
        if self._chunks_path.exists() and self._vectors_path.exists():
            raw = json.loads(self._chunks_path.read_text(encoding="utf-8"))
            self._chunks = [Chunk(**c) for c in raw]
            self._vectors = np.load(self._vectors_path)
        self._rebuild()

    def _save(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._chunks_path.write_text(
            json.dumps([c.model_dump() for c in self._chunks], ensure_ascii=False),
            encoding="utf-8",
        )
        np.save(self._vectors_path, self._vectors)

    def _rebuild(self) -> None:
        if len(self._chunks) == 0:
            self._index = None
            return
        self._index = faiss.IndexFlatIP(self._vectors.shape[1])
        self._index.add(self._vectors)

    @staticmethod
    def _normalize(vectors: list[list[float]]) -> np.ndarray:
        arr = np.asarray(vectors, dtype="float32")
        faiss.normalize_L2(arr)
        return arr

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        new = self._normalize(vectors)
        if self._vectors.size and self._vectors.shape[1] != new.shape[1]:
            raise ValueError(
                f"Embedding dimension changed ({self._vectors.shape[1]} -> {new.shape[1]}); "
                f"delete {self._dir} and re-ingest."
            )
        self._vectors = new if not self._vectors.size else np.vstack([self._vectors, new])
        self._chunks.extend(chunks)
        self._rebuild()
        self._save()

    def search(
        self, query_vector: list[float], top_k: int, query_text: str | None = None
    ) -> list[RetrievedChunk]:
        # Vector-only: query_text is accepted for interface parity with hybrid stores.
        if self._index is None:
            return []
        query = self._normalize([query_vector])
        scores, ids = self._index.search(query, min(top_k, len(self._chunks)))
        return [
            RetrievedChunk(chunk=self._chunks[i], score=float(s))
            for s, i in zip(scores[0], ids[0])
            if i != -1
        ]

    def delete_document(self, document_id: str) -> None:
        keep = [i for i, c in enumerate(self._chunks) if c.document_id != document_id]
        if len(keep) == len(self._chunks):
            return
        self._chunks = [self._chunks[i] for i in keep]
        self._vectors = self._vectors[keep] if keep else np.zeros((0, 0), dtype="float32")
        self._rebuild()
        self._save()

    def list_documents(self) -> dict[str, str]:
        """document_id -> filename"""
        return {c.document_id: c.filename for c in self._chunks}


def get_vector_store(settings: Settings) -> VectorStore:
    if settings.vector_store == "faiss":
        return FaissVectorStore(settings.index_dir)
    if settings.vector_store == "azure_search":
        from src.azure_clients.ai_search import get_search_store

        return get_search_store(settings.azure_search_endpoint, settings.azure_search_index)
    raise ValueError(f"Unknown vector store: {settings.vector_store}")
