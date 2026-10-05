from pydantic import BaseModel, Field


class PageText(BaseModel):
    """Text extracted from a single PDF page."""

    filename: str
    page_number: int  # 1-based
    text: str


class Chunk(BaseModel):
    """A searchable unit of text. Field names mirror the Azure AI Search index (Phase 3)."""

    id: str
    document_id: str
    filename: str
    page_number: int
    chunk_id: int
    content: str


class RetrievedChunk(BaseModel):
    chunk: Chunk
    score: float


class Citation(BaseModel):
    filename: str
    page_number: int


class ChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    top_k: int | None = Field(default=None, ge=1, le=20)


class DocumentInfo(BaseModel):
    document_id: str
    filename: str


class IngestResult(DocumentInfo):
    chunks: int


class Answer(BaseModel):
    question: str
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    sources: list[RetrievedChunk] = Field(default_factory=list)
