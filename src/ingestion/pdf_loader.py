import hashlib
import io
import re
from pathlib import Path

from pypdf import PdfReader

from src.models.schemas import PageText


def document_id_for(data: bytes) -> str:
    """Stable ID derived from file contents, so re-ingesting the same PDF replaces it."""
    return hashlib.sha256(data).hexdigest()[:16]


def _clean(text: str) -> str:
    text = text.replace("\x00", "")
    text = re.sub(r"-\n(?=\w)", "", text)  # re-join hyphenated line breaks
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def load_pdf_bytes(filename: str, data: bytes) -> list[PageText]:
    """Extract text page by page. Pages with no extractable text (e.g. scans) are skipped."""
    reader = PdfReader(io.BytesIO(data))
    pages = []
    for number, page in enumerate(reader.pages, start=1):
        text = _clean(page.extract_text() or "")
        if text:
            pages.append(PageText(filename=filename, page_number=number, text=text))
    return pages


def load_pdf(path: Path) -> list[PageText]:
    return load_pdf_bytes(path.name, path.read_bytes())
