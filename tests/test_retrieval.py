"""End-to-end pipeline tests with a fake embedder/LLM, so they run without Ollama or Azure."""

import hashlib

import numpy as np
import pytest
from reportlab.pdfgen import canvas

from src.config.settings import Settings
from src.ingestion.processor import ingest_pdf
from src.rag.generator import NOT_FOUND_MESSAGE
from src.rag.pipeline import RAGPipeline
from src.rag.retriever import Retriever
from src.rag.vector_store import FaissVectorStore


class BagOfWordsEmbedder:
    """Deterministic hashed bag-of-words embeddings: good enough to test retrieval wiring."""

    dim = 256

    def _vec(self, text: str) -> list[float]:
        v = np.zeros(self.dim, dtype="float32")
        for word in text.lower().split():
            word = word.strip(".,?!")
            v[int(hashlib.md5(word.encode()).hexdigest(), 16) % self.dim] += 1
        return v.tolist()

    def embed_documents(self, texts):
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


class EchoGenerator:
    def __init__(self, reply="Answer from context."):
        self.reply = reply
        self.last_user_prompt = None

    def generate(self, system_prompt, user_prompt):
        self.last_user_prompt = user_prompt
        return self.reply


def make_pdf(path, pages):
    c = canvas.Canvas(str(path))
    for text in pages:
        c.drawString(72, 720, text)
        c.showPage()
    c.save()


@pytest.fixture
def settings(tmp_path):
    return Settings(index_dir=tmp_path / "index", chunk_size=500, chunk_overlap=50)


@pytest.fixture
def indexed(tmp_path, settings):
    pdf = tmp_path / "cloud.pdf"
    make_pdf(
        pdf,
        [
            "Kubernetes clusters on Azure are managed by AKS.",
            "Terraform provisions infrastructure using HCL configuration files.",
        ],
    )
    embedder = BagOfWordsEmbedder()
    store = FaissVectorStore(settings.index_dir)
    count = ingest_pdf(pdf, embedder, store, settings)
    return pdf, embedder, store, count


def test_ingest_and_retrieve_correct_page(indexed):
    _, embedder, store, count = indexed
    assert count == 2
    results = Retriever(embedder, store, top_k=1).retrieve("What does Terraform provision?")
    assert results[0].chunk.page_number == 2
    assert results[0].chunk.filename == "cloud.pdf"


def test_store_persists_and_reingest_replaces(indexed, settings):
    pdf, embedder, store, _ = indexed
    reloaded = FaissVectorStore(settings.index_dir)
    assert len(reloaded.list_documents()) == 1
    ingest_pdf(pdf, embedder, reloaded, settings)  # same file -> same document_id
    assert len(reloaded.search(embedder.embed_query("AKS"), top_k=10)) == 2


def test_delete_document(indexed, settings):
    _, embedder, store, _ = indexed
    (doc_id,) = store.list_documents()
    store.delete_document(doc_id)
    assert store.search(embedder.embed_query("AKS"), top_k=5) == []
    assert FaissVectorStore(settings.index_dir).list_documents() == {}


def test_pipeline_returns_citations_and_context(indexed):
    _, embedder, store, _ = indexed
    generator = EchoGenerator()
    answer = RAGPipeline(Retriever(embedder, store, top_k=1), generator).ask("What manages AKS clusters?")
    assert "[cloud.pdf, page 1]" in generator.last_user_prompt
    assert [(c.filename, c.page_number) for c in answer.citations] == [("cloud.pdf", 1)]


def test_pipeline_keeps_only_inline_cited_pages(indexed):
    _, embedder, store, _ = indexed
    generator = EchoGenerator("Terraform provisions it [cloud.pdf, page 2].")
    answer = RAGPipeline(Retriever(embedder, store, top_k=2), generator).ask("Terraform AKS?")
    assert [(c.filename, c.page_number) for c in answer.citations] == [("cloud.pdf", 2)]


def test_pipeline_no_citations_when_not_found(indexed):
    _, embedder, store, _ = indexed
    answer = RAGPipeline(Retriever(embedder, store, top_k=2), EchoGenerator(NOT_FOUND_MESSAGE)).ask("Who won?")
    assert answer.citations == []


def test_pipeline_empty_index(tmp_path):
    store = FaissVectorStore(tmp_path / "empty")
    generator = EchoGenerator()
    answer = RAGPipeline(Retriever(BagOfWordsEmbedder(), store, top_k=3), generator).ask("Anything?")
    assert answer.answer == NOT_FOUND_MESSAGE
    assert generator.last_user_prompt is None
