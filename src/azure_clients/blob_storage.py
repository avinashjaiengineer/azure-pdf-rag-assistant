from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import BlobServiceClient, ContainerClient, ContentSettings

from src.azure_clients.credential import get_credential
from src.ingestion.storage import DocumentNotFoundError, safe_pdf_name


class BlobDocumentStorage:
    """Original PDFs in an Azure Blob container, one blob per filename."""

    def __init__(self, container: ContainerClient):
        self._container = container

    def save(self, filename: str, data: bytes) -> None:
        self._container.upload_blob(
            safe_pdf_name(filename),
            data,
            overwrite=True,
            content_settings=ContentSettings(content_type="application/pdf"),
        )

    def read(self, filename: str) -> bytes:
        try:
            return self._container.download_blob(safe_pdf_name(filename)).readall()
        except ResourceNotFoundError as exc:
            raise DocumentNotFoundError(filename) from exc

    def list(self) -> list[str]:
        return sorted(b.name for b in self._container.list_blobs() if b.name.lower().endswith(".pdf"))

    def delete(self, filename: str) -> None:
        try:
            self._container.delete_blob(safe_pdf_name(filename), delete_snapshots="include")
        except ResourceNotFoundError:
            pass


def get_blob_storage(account_url: str, container: str) -> BlobDocumentStorage:
    if not account_url:
        raise ValueError("AZURE_STORAGE_ACCOUNT_URL is not set")
    # Shared-key access is disabled on the account; Entra ID is the only way in.
    service = BlobServiceClient(account_url, credential=get_credential())
    return BlobDocumentStorage(service.get_container_client(container))
