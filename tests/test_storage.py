from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

from src.azure_clients.blob_storage import BlobDocumentStorage
from src.config.settings import Settings
from src.ingestion.processor import ingest_document
from src.ingestion.storage import LocalDocumentStorage, safe_pdf_name
from src.rag.vector_store import FaissVectorStore
from tests.test_retrieval import BagOfWordsEmbedder, make_pdf


@pytest.mark.parametrize(
    "raw,expected",
    [("a.pdf", "a.pdf"), ("../../etc/x.PDF", "x.PDF"), ("C:\\docs\\b.pdf", "b.pdf")],
)
def test_safe_pdf_name(raw, expected):
    assert safe_pdf_name(raw) == expected


@pytest.mark.parametrize("raw", ["notes.txt", "", "dir/"])
def test_safe_pdf_name_rejects(raw):
    with pytest.raises(ValueError):
        safe_pdf_name(raw)


def test_local_storage_roundtrip(tmp_path):
    storage = LocalDocumentStorage(tmp_path / "raw")
    storage.save("../evil/a.pdf", b"%PDF-1")
    assert (tmp_path / "raw" / "a.pdf").exists()
    assert storage.list() == ["a.pdf"]
    assert storage.read("a.pdf") == b"%PDF-1"
    storage.delete("a.pdf")
    storage.delete("a.pdf")  # idempotent
    assert storage.list() == []


class FakeContainer:
    def __init__(self):
        self.blobs = {}

    def upload_blob(self, name, data, overwrite, content_settings):
        assert overwrite and content_settings.content_type == "application/pdf"
        self.blobs[name] = data

    def download_blob(self, name):
        return SimpleNamespace(readall=lambda: self.blobs[name])

    def list_blobs(self):
        return [SimpleNamespace(name=n) for n in self.blobs]

    def delete_blob(self, name, delete_snapshots):
        if name not in self.blobs:
            raise ResourceNotFoundError("missing")
        del self.blobs[name]


def test_blob_storage_roundtrip():
    container = FakeContainer()
    storage = BlobDocumentStorage(container)
    storage.save("b.pdf", b"2")
    storage.save("a.pdf", b"1")
    container.blobs["readme.txt"] = b"ignored"
    assert storage.list() == ["a.pdf", "b.pdf"]
    assert storage.read("a.pdf") == b"1"
    storage.delete("a.pdf")
    storage.delete("a.pdf")  # missing blob is not an error
    assert storage.list() == ["b.pdf"]


def test_new_version_of_same_filename_replaces_old(tmp_path):
    settings = Settings(index_dir=tmp_path / "index")
    store = FaissVectorStore(settings.index_dir)
    embedder = BagOfWordsEmbedder()
    v1, v2 = tmp_path / "v1.pdf", tmp_path / "v2.pdf"
    make_pdf(v1, ["Version one mentions apples."])
    make_pdf(v2, ["Version two mentions bananas."])

    ingest_document("report.pdf", v1.read_bytes(), embedder, store, settings)
    ingest_document("report.pdf", v2.read_bytes(), embedder, store, settings)

    assert len(store.list_documents()) == 1
    (hit,) = store.search(embedder.embed_query("bananas"), top_k=5)
    assert "bananas" in hit.chunk.content
