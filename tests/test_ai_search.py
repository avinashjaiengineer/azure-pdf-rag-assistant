"""AzureSearchVectorStore against fake SDK clients, so these run without Azure."""

from types import SimpleNamespace

import pytest
from azure.core.exceptions import ResourceNotFoundError

from src.azure_clients.ai_search import AzureSearchVectorStore, _odata_str, build_index
from src.models.schemas import Chunk


class FakeIndexClient:
    def __init__(self):
        self.indexes = {}

    def get_index(self, name):
        if name not in self.indexes:
            raise ResourceNotFoundError("missing")
        return self.indexes[name]

    def create_index(self, index):
        self.indexes[index.name] = index


class FakeSearchClient:
    def __init__(self):
        self.docs = {}
        self.last_search = None

    def upload_documents(self, docs):
        self.docs.update({d["id"]: d for d in docs})
        return [SimpleNamespace(key=d["id"], succeeded=True) for d in docs]

    def delete_documents(self, keys):
        for k in keys:
            self.docs.pop(k["id"], None)

    def search(self, search_text=None, filter=None, select=None, top=None, vector_queries=None):
        self.last_search = {"search_text": search_text, "vector_queries": vector_queries}
        rows = list(self.docs.values())
        if filter and filter.startswith("document_id eq "):
            doc_id = filter.removeprefix("document_id eq ").strip("'")
            rows = [r for r in rows if r["document_id"] == doc_id]
        elif filter == "chunk_id eq 0":
            rows = [r for r in rows if r["chunk_id"] == 0]
        return [{**{k: r[k] for k in select}, "@search.score": 0.5} for r in rows[:top]]


def chunk(doc, n, page=1):
    return Chunk(id=f"{doc}-{n}", document_id=doc, filename=f"{doc}.pdf", page_number=page, chunk_id=n, content=f"text {n}")


@pytest.fixture
def store():
    return AzureSearchVectorStore(FakeIndexClient(), FakeSearchClient(), "test-index")


def test_index_schema_vector_field():
    index = build_index("x", 1536)
    vector = next(f for f in index.fields if f.name == "content_vector")
    assert vector.vector_search_dimensions == 1536
    assert next(f for f in index.fields if f.key).name == "id"


def test_add_creates_index_and_uploads(store):
    store.add([chunk("a", 0), chunk("a", 1)], [[0.1] * 4, [0.2] * 4])
    assert "test-index" in store._index_client.indexes
    assert store._search.docs["a-1"]["content_vector"] == [0.2] * 4


def test_add_rejects_dimension_mismatch(store):
    store._index_client.create_index(build_index("test-index", 8))
    with pytest.raises(ValueError, match="8-dim"):
        store.add([chunk("a", 0)], [[0.1] * 4])


def test_search_is_hybrid_and_maps_chunks(store):
    store.add([chunk("a", 0, page=3)], [[0.1] * 4])
    results = store.search([0.1] * 4, top_k=5, query_text="what is text")
    assert store._search.last_search["search_text"] == "what is text"
    assert store._search.last_search["vector_queries"][0].fields == "content_vector"
    assert results[0].chunk.page_number == 3


def test_list_and_delete_documents(store):
    store.add([chunk("a", 0), chunk("a", 1), chunk("b", 0)], [[0.1] * 4] * 3)
    assert store.list_documents() == {"a": "a.pdf", "b": "b.pdf"}
    store.delete_document("a")
    assert store.list_documents() == {"b": "b.pdf"}


def test_missing_index_behaves_as_empty():
    class MissingSearch(FakeSearchClient):
        def search(self, **kwargs):
            raise ResourceNotFoundError("no index")

    empty = AzureSearchVectorStore(FakeIndexClient(), MissingSearch(), "test-index")
    assert empty.search([0.1], top_k=3, query_text="q") == []
    assert empty.list_documents() == {}


def test_odata_quotes_escaped():
    assert _odata_str("o'brien") == "'o''brien'"
