import pytest

from src.ingestion.chunker import chunk_pages, split_text
from src.models.schemas import PageText


def test_short_text_is_single_chunk():
    assert split_text("Hello world.", chunk_size=100, chunk_overlap=10) == ["Hello world."]


def test_chunks_respect_size_limit():
    text = " ".join(f"word{i}" for i in range(2000))
    chunks = split_text(text, chunk_size=200, chunk_overlap=40)
    assert len(chunks) > 1
    assert all(len(c) <= 200 for c in chunks)


def test_chunks_overlap():
    text = " ".join(f"w{i}" for i in range(500))
    chunks = split_text(text, chunk_size=100, chunk_overlap=30)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert nxt.split()[0] in prev.split()


def test_prefers_paragraph_breaks():
    para = "A" * 60
    text = f"{para}\n\n{para}\n\n{para}"
    chunks = split_text(text, chunk_size=100, chunk_overlap=0)
    assert chunks[0] == para


def test_no_text_lost():
    words = [f"t{i}" for i in range(1000)]
    chunks = split_text(" ".join(words), chunk_size=150, chunk_overlap=20)
    assert set(" ".join(chunks).split()) == set(words)


@pytest.mark.parametrize("size,overlap", [(0, 0), (100, 100), (100, -1)])
def test_invalid_params(size, overlap):
    with pytest.raises(ValueError):
        split_text("abc", size, overlap)


def test_chunk_pages_keeps_page_numbers():
    pages = [
        PageText(filename="a.pdf", page_number=1, text="first page " * 50),
        PageText(filename="a.pdf", page_number=2, text="second page"),
    ]
    chunks = chunk_pages(pages, "doc1", chunk_size=200, chunk_overlap=20)
    assert chunks[-1].page_number == 2
    assert chunks[-1].content == "second page"
    assert [c.chunk_id for c in chunks] == list(range(len(chunks)))
    assert len({c.id for c in chunks}) == len(chunks)
