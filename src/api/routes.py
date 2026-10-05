from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from pypdf.errors import PdfReadError

from src.api.services import Services
from src.ingestion.pdf_loader import document_id_for
from src.ingestion.processor import ingest_document
from src.ingestion.storage import DocumentNotFoundError, safe_pdf_name
from src.models.schemas import Answer, ChatRequest, DocumentInfo, IngestResult

router = APIRouter()


def get_services(request: Request) -> Services:
    return request.app.state.services


ServicesDep = Annotated[Services, Depends(get_services)]


def _index(services: Services, filename: str, data: bytes) -> IngestResult:
    try:
        chunks = ingest_document(filename, data, services.embedder, services.store, services.settings)
    except PdfReadError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"Could not read PDF: {exc}") from exc
    if chunks == 0:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "No extractable text found (scanned PDFs need OCR, which is not supported yet).",
        )
    return IngestResult(document_id=document_id_for(data), filename=filename, chunks=chunks)


@router.get("/health")
def health(services: ServicesDep) -> dict:
    s = services.settings
    return {
        "status": "ok",
        "llm_provider": s.llm_provider,
        "embedding_provider": s.embedding_provider,
        "vector_store": s.vector_store,
        "document_storage": s.document_storage,
    }


@router.post("/upload", status_code=status.HTTP_201_CREATED)
def upload(file: UploadFile, services: ServicesDep) -> IngestResult:
    """Store a PDF, then extract, chunk, embed and index it."""
    try:
        filename = safe_pdf_name(file.filename or "")
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc

    limit = services.settings.max_upload_mb * 1024 * 1024
    data = file.file.read(limit + 1)
    if len(data) > limit:
        raise HTTPException(
            status.HTTP_413_CONTENT_TOO_LARGE, f"File exceeds {services.settings.max_upload_mb} MB"
        )
    if not data.startswith(b"%PDF-"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "File is not a PDF")

    # Index first so a PDF that fails to parse is rejected without being stored;
    # if storing then fails, roll back the index so the two never disagree.
    result = _index(services, filename, data)
    try:
        services.storage.save(filename, data)
    except Exception:
        services.store.delete_document(result.document_id)
        raise
    return result


@router.post("/ingest")
def ingest(services: ServicesDep, filename: str | None = None) -> list[IngestResult]:
    """Re-index one stored PDF, or all of them (e.g. after changing chunk settings)."""
    names = [filename] if filename else services.storage.list()
    results = []
    for name in names:
        try:
            data = services.storage.read(name)
        except (DocumentNotFoundError, ValueError) as exc:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"{name} not found in storage") from exc
        results.append(_index(services, name, data))
    return results


@router.post("/chat")
def chat(body: ChatRequest, services: ServicesDep) -> Answer:
    return services.pipeline.ask(body.question.strip(), body.top_k)


@router.get("/documents")
def list_documents(services: ServicesDep) -> list[DocumentInfo]:
    docs = services.store.list_documents()
    return sorted(
        (DocumentInfo(document_id=i, filename=f) for i, f in docs.items()), key=lambda d: d.filename
    )


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(document_id: str, services: ServicesDep) -> None:
    filename = services.store.list_documents().get(document_id)
    if filename is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")
    services.store.delete_document(document_id)
    services.storage.delete(filename)
