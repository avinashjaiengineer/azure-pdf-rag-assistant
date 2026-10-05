import re

from src.config.settings import Settings, get_settings
from src.models.schemas import Answer, Citation, RetrievedChunk
from src.rag.embeddings import get_embedder
from src.rag.generator import (
    NOT_FOUND_MESSAGE,
    SYSTEM_PROMPT,
    Generator,
    build_user_prompt,
    get_generator,
)
from src.rag.retriever import Retriever
from src.rag.vector_store import get_vector_store

# Matches labels like "[terraform.pdf, page 3]" written by the model.
_INLINE_CITATION = re.compile(r"\[([^\[\],]+?),\s*page\s+(\d+)\]", re.IGNORECASE)


class RAGPipeline:
    def __init__(self, retriever: Retriever, generator: Generator):
        self._retriever = retriever
        self._generator = generator

    def ask(self, question: str, top_k: int | None = None) -> Answer:
        sources = self._retriever.retrieve(question, top_k)
        if not sources:
            return Answer(question=question, answer=NOT_FOUND_MESSAGE)

        text = self._generator.generate(SYSTEM_PROMPT, build_user_prompt(question, sources))

        return Answer(
            question=question, answer=text, citations=extract_citations(text, sources), sources=sources
        )


def extract_citations(text: str, sources: list[RetrievedChunk]) -> list[Citation]:
    """Pages the answer cites inline; falls back to all retrieved pages if it cites none."""
    if NOT_FOUND_MESSAGE in text:
        return []
    retrieved = list(dict.fromkeys((r.chunk.filename, r.chunk.page_number) for r in sources))
    cited = {(f.strip(), int(p)) for f, p in _INLINE_CITATION.findall(text)}
    keys = [k for k in retrieved if k in cited] or retrieved
    return [Citation(filename=f, page_number=p) for f, p in keys]


def build_pipeline(settings: Settings | None = None) -> RAGPipeline:
    settings = settings or get_settings()
    retriever = Retriever(get_embedder(settings), get_vector_store(settings), settings.top_k)
    return RAGPipeline(retriever, get_generator(settings))
