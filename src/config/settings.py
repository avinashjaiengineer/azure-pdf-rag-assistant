"""Central configuration, loaded from environment variables / .env.

Each phase swaps a backend by changing one setting rather than code:
  Phase 1: LLM_PROVIDER=ollama  EMBEDDING_PROVIDER=ollama  VECTOR_STORE=faiss
  Phase 2: LLM_PROVIDER=azure   EMBEDDING_PROVIDER=azure
  Phase 3: VECTOR_STORE=azure_search
  Phase 4: DOCUMENT_STORAGE=blob
"""

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    # Backend selection
    llm_provider: Literal["ollama", "azure"] = "ollama"
    embedding_provider: Literal["ollama", "azure"] = "ollama"
    vector_store: Literal["faiss", "azure_search"] = "faiss"
    document_storage: Literal["local", "blob"] = "local"

    # Local Ollama (Phase 1)
    ollama_base_url: str = "http://localhost:11434"
    ollama_chat_model: str = "qwen3:8b"
    ollama_embedding_model: str = "nomic-embed-text"
    ollama_timeout_seconds: float = 300.0

    # Azure OpenAI (Phase 2) — Entra ID auth via DefaultAzureCredential, no keys
    azure_openai_endpoint: str = ""
    azure_openai_chat_deployment: str = "gpt-5-mini"
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    # Set for reasoning models (gpt-5 family), which reject `temperature`.
    # Leave empty for non-reasoning models to send `temperature` instead.
    azure_openai_reasoning_effort: str | None = "low"
    azure_openai_max_output_tokens: int = 1500
    azure_openai_timeout_seconds: float = 60.0

    # Azure AI Search (Phase 3) — Entra ID auth, hybrid keyword + vector retrieval
    azure_search_endpoint: str = ""
    # Defaults to pdf-chunks-<embedding_provider>, mirroring the per-provider FAISS dirs.
    azure_search_index: str | None = None

    # Azure Blob Storage (Phase 4) — Entra ID auth (shared-key access is disabled)
    azure_storage_account_url: str = ""
    azure_storage_container: str = "documents"

    # API
    max_upload_mb: int = 20

    # Chunking
    chunk_size: int = 1000
    chunk_overlap: int = 150

    # Retrieval / generation
    top_k: int = 5
    temperature: float = 0.1

    # Local paths
    raw_data_dir: Path = PROJECT_ROOT / "data" / "raw"
    # Defaults to data/processed/faiss/<embedding_provider>, so switching embedding
    # providers never mixes vectors of different dimensions in one index.
    index_dir: Path | None = None

    @model_validator(mode="after")
    def _default_index_names(self) -> "Settings":
        if self.index_dir is None:
            self.index_dir = PROJECT_ROOT / "data" / "processed" / "faiss" / self.embedding_provider
        if self.azure_search_index is None:
            self.azure_search_index = f"pdf-chunks-{self.embedding_provider}"
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
