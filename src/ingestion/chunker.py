from src.models.schemas import Chunk, PageText

# Preferred break points, strongest first.
_SEPARATORS = ("\n\n", "\n", ". ", " ")


def split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """Sliding-window split that prefers to break on paragraph/sentence/word boundaries."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")

    text = text.strip()
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + chunk_size, len(text))
        if end < len(text):
            window = text[start:end]
            for sep in _SEPARATORS:
                cut = window.rfind(sep)
                # Only accept a break in the back half, otherwise chunks get tiny.
                if cut > chunk_size // 2:
                    end = start + cut + len(sep)
                    break
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= len(text):
            break
        next_start = end - chunk_overlap
        # Snap the overlap start forward to a word boundary.
        space = text.find(" ", next_start, end)
        start = space + 1 if space != -1 else next_start
    return chunks


def chunk_pages(
    pages: list[PageText], document_id: str, chunk_size: int, chunk_overlap: int
) -> list[Chunk]:
    """Chunk each page separately so every chunk maps to exactly one page for citations."""
    chunks: list[Chunk] = []
    for page in pages:
        for piece in split_text(page.text, chunk_size, chunk_overlap):
            n = len(chunks)
            chunks.append(
                Chunk(
                    id=f"{document_id}-{n:05d}",
                    document_id=document_id,
                    filename=page.filename,
                    page_number=page.page_number,
                    chunk_id=n,
                    content=piece,
                )
            )
    return chunks
