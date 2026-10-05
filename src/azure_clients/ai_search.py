from azure.core.exceptions import ResourceNotFoundError
from azure.search.documents import SearchClient
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    HnswAlgorithmConfiguration,
    HnswParameters,
    SearchableField,
    SearchField,
    SearchFieldDataType,
    SearchIndex,
    SimpleField,
    VectorSearch,
    VectorSearchAlgorithmMetric,
    VectorSearchProfile,
)
from azure.search.documents.models import VectorizedQuery

from src.azure_clients.credential import get_credential
from src.models.schemas import Chunk, RetrievedChunk

_VECTOR_FIELD = "content_vector"
_PROFILE = "hnsw-cosine"
_SELECT = ["id", "document_id", "filename", "page_number", "chunk_id", "content"]
_UPLOAD_BATCH = 100  # 1536-dim vectors are ~30 KB of JSON each; stay well under the 16 MB request cap


def build_index(name: str, dimensions: int) -> SearchIndex:
    """Index schema; field names match the Chunk model so documents map 1:1."""
    return SearchIndex(
        name=name,
        fields=[
            SimpleField(name="id", type=SearchFieldDataType.String, key=True),
            SimpleField(name="document_id", type=SearchFieldDataType.String, filterable=True),
            SimpleField(name="filename", type=SearchFieldDataType.String, filterable=True, facetable=True),
            SimpleField(name="page_number", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
            SimpleField(name="chunk_id", type=SearchFieldDataType.Int32, filterable=True, sortable=True),
            SearchableField(name="content", type=SearchFieldDataType.String, analyzer_name="en.microsoft"),
            SearchField(
                name=_VECTOR_FIELD,
                type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                searchable=True,
                vector_search_dimensions=dimensions,
                vector_search_profile_name=_PROFILE,
                # Vectors are only needed for search, not returned: not storing the raw copy
                # roughly halves vector storage, which matters on the 50 MB free tier.
                stored=False,
                hidden=True,
            ),
        ],
        vector_search=VectorSearch(
            algorithms=[
                HnswAlgorithmConfiguration(
                    name="hnsw",
                    parameters=HnswParameters(metric=VectorSearchAlgorithmMetric.COSINE),
                )
            ],
            profiles=[VectorSearchProfile(name=_PROFILE, algorithm_configuration_name="hnsw")],
        ),
    )


def _odata_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


class AzureSearchVectorStore:
    """Hybrid (BM25 keyword + vector, fused with RRF) retrieval on Azure AI Search.

    The index is created on first add(), sized to the embedding dimension actually produced.
    """

    def __init__(self, index_client: SearchIndexClient, search_client: SearchClient, index_name: str):
        self._index_client = index_client
        self._search = search_client
        self._index_name = index_name
        self._index_ready = False

    def _ensure_index(self, dimensions: int) -> None:
        if self._index_ready:
            return
        try:
            existing = self._index_client.get_index(self._index_name)
            field = next(f for f in existing.fields if f.name == _VECTOR_FIELD)
            if field.vector_search_dimensions != dimensions:
                raise ValueError(
                    f"Index '{self._index_name}' expects {field.vector_search_dimensions}-dim vectors, "
                    f"got {dimensions}. Delete the index or set AZURE_SEARCH_INDEX to a new name."
                )
        except ResourceNotFoundError:
            self._index_client.create_index(build_index(self._index_name, dimensions))
        self._index_ready = True

    def add(self, chunks: list[Chunk], vectors: list[list[float]]) -> None:
        if len(chunks) != len(vectors):
            raise ValueError("chunks and vectors must have the same length")
        if not chunks:
            return
        self._ensure_index(len(vectors[0]))
        docs = [{**c.model_dump(), _VECTOR_FIELD: v} for c, v in zip(chunks, vectors)]
        for i in range(0, len(docs), _UPLOAD_BATCH):
            results = self._search.upload_documents(docs[i : i + _UPLOAD_BATCH])
            failed = [r.key for r in results if not r.succeeded]
            if failed:
                raise RuntimeError(f"Failed to index {len(failed)} chunks, e.g. {failed[:3]}")

    def search(
        self, query_vector: list[float], top_k: int, query_text: str | None = None
    ) -> list[RetrievedChunk]:
        vector_query = VectorizedQuery(
            vector=query_vector,
            # Over-fetch vector candidates so RRF has more to fuse with keyword results.
            k_nearest_neighbors=max(top_k * 5, 50),
            fields=_VECTOR_FIELD,
        )
        try:
            results = self._search.search(
                search_text=query_text,  # None -> pure vector search
                vector_queries=[vector_query],
                select=_SELECT,
                top=top_k,
            )
            return [
                RetrievedChunk(
                    chunk=Chunk(**{k: r[k] for k in _SELECT}), score=r["@search.score"]
                )
                for r in results
            ]
        except ResourceNotFoundError:
            return []  # nothing ingested yet

    def delete_document(self, document_id: str) -> None:
        try:
            while True:
                keys = [
                    {"id": r["id"]}
                    for r in self._search.search(
                        search_text="*",
                        filter=f"document_id eq {_odata_str(document_id)}",
                        select=["id"],
                        top=1000,
                    )
                ]
                if not keys:
                    return
                self._search.delete_documents(keys)
                if len(keys) < 1000:
                    return
        except ResourceNotFoundError:
            return

    def list_documents(self) -> dict[str, str]:
        """document_id -> filename. Every document has exactly one chunk with chunk_id 0."""
        try:
            results = self._search.search(
                search_text="*", filter="chunk_id eq 0", select=["document_id", "filename"], top=1000
            )
            return {r["document_id"]: r["filename"] for r in results}
        except ResourceNotFoundError:
            return {}


def get_search_store(endpoint: str, index_name: str) -> AzureSearchVectorStore:
    if not endpoint:
        raise ValueError("AZURE_SEARCH_ENDPOINT is not set")
    credential = get_credential()
    return AzureSearchVectorStore(
        SearchIndexClient(endpoint, credential),
        SearchClient(endpoint, index_name, credential),
        index_name,
    )
