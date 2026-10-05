from pathlib import Path
from typing import Protocol

from src.config.settings import Settings


def safe_pdf_name(filename: str) -> str:
    """Strip any directory components and require a .pdf extension."""
    name = Path(filename.replace("\\", "/")).name.strip()
    if not name or not name.lower().endswith(".pdf"):
        raise ValueError(f"Not a PDF filename: {filename!r}")
    return name


class DocumentNotFoundError(FileNotFoundError):
    """Raised by every DocumentStorage.read() when the file does not exist."""


class DocumentStorage(Protocol):
    """Where the original PDFs live. Keyed by filename."""

    def save(self, filename: str, data: bytes) -> None: ...

    def read(self, filename: str) -> bytes: ...

    def list(self) -> list[str]: ...

    def delete(self, filename: str) -> None: ...


class LocalDocumentStorage:
    def __init__(self, directory: Path):
        self._dir = directory

    def save(self, filename: str, data: bytes) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / safe_pdf_name(filename)).write_bytes(data)

    def read(self, filename: str) -> bytes:
        try:
            return (self._dir / safe_pdf_name(filename)).read_bytes()
        except FileNotFoundError as exc:
            raise DocumentNotFoundError(filename) from exc

    def list(self) -> list[str]:
        return sorted(p.name for p in self._dir.glob("*") if p.suffix.lower() == ".pdf")

    def delete(self, filename: str) -> None:
        (self._dir / safe_pdf_name(filename)).unlink(missing_ok=True)


def get_document_storage(settings: Settings) -> DocumentStorage:
    if settings.document_storage == "local":
        return LocalDocumentStorage(settings.raw_data_dir)
    if settings.document_storage == "blob":
        from src.azure_clients.blob_storage import get_blob_storage

        return get_blob_storage(settings.azure_storage_account_url, settings.azure_storage_container)
    raise ValueError(f"Unknown document storage: {settings.document_storage}")
