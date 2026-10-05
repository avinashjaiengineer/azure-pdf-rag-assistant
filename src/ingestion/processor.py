from pathlib import Path

from src.config.settings import Settings
from src.ingestion.chunker import chunk_pages
from src.ingestion.pdf_loader import document_id_for, load_pdf_bytes
from src.rag.embeddings import Embedder
from src.rag.vector_store import VectorStore


def ingest_document(
    filename: str, data: bytes, embedder: Embedder, store: VectorStore, settings: Settings
) -> int:
    """PDF bytes -> pages -> chunks -> embeddings -> vector store. Returns the number of chunks indexed.

    A filename maps to one stored PDF, so any previously indexed version under the same
    name is replaced, as is an identical file indexed under this ID.
    """
    document_id = document_id_for(data)
    pages = load_pdf_bytes(filename, data)
    chunks = chunk_pages(pages, document_id, settings.chunk_size, settings.chunk_overlap)
    if not chunks:
        return 0
    vectors = embedder.embed_documents([c.content for c in chunks])
    for old_id, old_name in store.list_documents().items():
        if old_name == filename and old_id != document_id:
            store.delete_document(old_id)
    store.delete_document(document_id)
    store.add(chunks, vectors)
    return len(chunks)


def ingest_pdf(path: Path, embedder: Embedder, store: VectorStore, settings: Settings) -> int:
    return ingest_document(path.name, path.read_bytes(), embedder, store, settings)
