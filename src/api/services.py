from dataclasses import dataclass

from src.config.settings import Settings
from src.ingestion.storage import DocumentStorage, get_document_storage
from src.rag.embeddings import Embedder, get_embedder
from src.rag.generator import get_generator
from src.rag.pipeline import RAGPipeline
from src.rag.retriever import Retriever
from src.rag.vector_store import VectorStore, get_vector_store


@dataclass
class Services:
    """Every backend the API needs, built once per process."""

    settings: Settings
    embedder: Embedder
    store: VectorStore
    storage: DocumentStorage
    pipeline: RAGPipeline


def build_services(settings: Settings) -> Services:
    embedder = get_embedder(settings)
    store = get_vector_store(settings)
    retriever = Retriever(embedder, store, settings.top_k)
    return Services(
        settings=settings,
        embedder=embedder,
        store=store,
        storage=get_document_storage(settings),
        pipeline=RAGPipeline(retriever, get_generator(settings)),
    )
