"""API tests with local fakes (FAISS in tmp, fake embedder/LLM): no Ollama or Azure needed."""

import pytest
from fastapi.testclient import TestClient

from src.api.main import create_app
from src.api.services import Services
from src.config.settings import Settings
from src.ingestion.storage import LocalDocumentStorage
from src.rag.pipeline import RAGPipeline
from src.rag.retriever import Retriever
from src.rag.vector_store import FaissVectorStore
from tests.test_retrieval import BagOfWordsEmbedder, EchoGenerator, make_pdf


@pytest.fixture
def services(tmp_path):
    settings = Settings(index_dir=tmp_path / "index", raw_data_dir=tmp_path / "raw", max_upload_mb=1)
    embedder = BagOfWordsEmbedder()
    store = FaissVectorStore(settings.index_dir)
    return Services(
        settings=settings,
        embedder=embedder,
        store=store,
        storage=LocalDocumentStorage(settings.raw_data_dir),
        pipeline=RAGPipeline(Retriever(embedder, store, 3), EchoGenerator("See [aks.pdf, page 1].")),
    )


@pytest.fixture
def client(services):
    with TestClient(create_app(services)) as c:
        yield c


@pytest.fixture
def pdf_bytes(tmp_path):
    path = tmp_path / "source.pdf"
    make_pdf(path, ["AKS is managed Kubernetes on Azure."])
    return path.read_bytes()


def upload(client, name, data):
    return client.post("/upload", files={"file": (name, data, "application/pdf")})


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"


def test_upload_list_chat_delete(client, services, pdf_bytes):
    r = upload(client, "aks.pdf", pdf_bytes)
    assert r.status_code == 201
    doc = r.json()
    assert doc["filename"] == "aks.pdf" and doc["chunks"] == 1
    assert services.storage.list() == ["aks.pdf"]

    assert client.get("/documents").json() == [{"document_id": doc["document_id"], "filename": "aks.pdf"}]

    answer = client.post("/chat", json={"question": "What is AKS?"}).json()
    assert answer["citations"] == [{"filename": "aks.pdf", "page_number": 1}]
    assert answer["sources"][0]["chunk"]["content"].startswith("AKS")

    assert client.delete(f"/documents/{doc['document_id']}").status_code == 204
    assert client.get("/documents").json() == []
    assert services.storage.list() == []


def test_ingest_reindexes_from_storage(client, services, pdf_bytes):
    services.storage.save("stored.pdf", pdf_bytes)
    r = client.post("/ingest")
    assert r.status_code == 200
    assert [d["filename"] for d in r.json()] == ["stored.pdf"]
    assert client.post("/ingest", params={"filename": "missing.pdf"}).status_code == 404


@pytest.mark.parametrize(
    "name,data,code",
    [
        ("notes.txt", b"%PDF-1.4", 400),  # wrong extension
        ("fake.pdf", b"hello", 400),  # not a PDF
        ("big.pdf", b"%PDF-" + b"0" * (1024 * 1024), 413),  # over max_upload_mb=1
        ("broken.pdf", b"%PDF-1.4 garbage", 422),  # unparseable
    ],
    ids=["wrong-extension", "not-a-pdf", "too-large", "unparseable"],
)
def test_upload_rejects_bad_files(client, services, name, data, code):
    assert upload(client, name, data).status_code == code
    assert services.storage.list() == []  # nothing stored on rejection


def test_chat_validation(client):
    assert client.post("/chat", json={"question": ""}).status_code == 422
    assert client.post("/chat", json={"question": "q", "top_k": 50}).status_code == 422


def test_delete_unknown_document(client):
    assert client.delete("/documents/nope").status_code == 404
