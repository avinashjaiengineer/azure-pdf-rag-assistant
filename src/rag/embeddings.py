from typing import TYPE_CHECKING, Protocol

import httpx

from src.config.settings import Settings

if TYPE_CHECKING:
    from openai import OpenAI


class Embedder(Protocol):
    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class OllamaEmbedder:
    """Local embeddings via Ollama's /api/embed endpoint."""

    def __init__(self, base_url: str, model: str, timeout: float, batch_size: int = 32):
        self._client = httpx.Client(base_url=base_url, timeout=timeout)
        self._model = model
        self._batch_size = batch_size

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.post("/api/embed", json={"model": self._model, "input": texts})
        response.raise_for_status()
        return response.json()["embeddings"]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        # nomic-embed-text is trained with task prefixes; harmless for other models.
        prefixed = [f"search_document: {t}" for t in texts]
        vectors: list[list[float]] = []
        for i in range(0, len(prefixed), self._batch_size):
            vectors.extend(self._embed(prefixed[i : i + self._batch_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([f"search_query: {text}"])[0]


class AzureOpenAIEmbedder:
    """Embeddings from an Azure OpenAI deployment (e.g. text-embedding-3-small, 1536 dims)."""

    def __init__(self, client: "OpenAI", deployment: str, batch_size: int = 64):
        self._client = client
        self._deployment = deployment
        self._batch_size = batch_size

    def _embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self._deployment, input=texts)
        return [item.embedding for item in sorted(response.data, key=lambda d: d.index)]

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        vectors: list[list[float]] = []
        for i in range(0, len(texts), self._batch_size):
            vectors.extend(self._embed(texts[i : i + self._batch_size]))
        return vectors

    def embed_query(self, text: str) -> list[float]:
        return self._embed([text])[0]


def get_embedder(settings: Settings) -> Embedder:
    if settings.embedding_provider == "ollama":
        return OllamaEmbedder(
            settings.ollama_base_url,
            settings.ollama_embedding_model,
            settings.ollama_timeout_seconds,
        )
    if settings.embedding_provider == "azure":
        from src.azure_clients.openai_client import get_openai_client

        client = get_openai_client(settings.azure_openai_endpoint, settings.azure_openai_timeout_seconds)
        return AzureOpenAIEmbedder(client, settings.azure_openai_embedding_deployment)
    raise ValueError(f"Unknown embedding provider: {settings.embedding_provider}")
