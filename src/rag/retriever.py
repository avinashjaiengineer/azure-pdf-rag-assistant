from src.models.schemas import RetrievedChunk
from src.rag.embeddings import Embedder
from src.rag.vector_store import VectorStore


class Retriever:
    def __init__(self, embedder: Embedder, store: VectorStore, top_k: int):
        self._embedder = embedder
        self._store = store
        self._top_k = top_k

    def retrieve(self, question: str, top_k: int | None = None) -> list[RetrievedChunk]:
        query_vector = self._embedder.embed_query(question)
        return self._store.search(query_vector, top_k or self._top_k, query_text=question)
