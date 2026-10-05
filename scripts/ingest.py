"""Upload PDFs to document storage and index them into the vector store.

Usage:
    python -m scripts.ingest                 # (re)index every PDF already in storage
    python -m scripts.ingest path/to/a.pdf   # upload these files to storage, then index them
    python -m scripts.ingest --list          # show indexed documents
    python -m scripts.ingest --delete <document_id>   # remove from the index and storage

Storage is data/raw/ (DOCUMENT_STORAGE=local) or an Azure Blob container (DOCUMENT_STORAGE=blob).
"""

import argparse
import sys
import time
from pathlib import Path

from src.config.settings import get_settings
from src.ingestion.processor import ingest_document
from src.ingestion.storage import get_document_storage
from src.rag.embeddings import get_embedder
from src.rag.vector_store import get_vector_store


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--delete", metavar="DOCUMENT_ID")
    args = parser.parse_args()

    settings = get_settings()
    store = get_vector_store(settings)
    storage = get_document_storage(settings)

    if args.list:
        docs = store.list_documents()
        for doc_id, filename in docs.items():
            print(f"{doc_id}  {filename}")
        if not docs:
            print("No documents indexed.")
        return 0

    if args.delete:
        filename = store.list_documents().get(args.delete)
        store.delete_document(args.delete)
        if filename:
            storage.delete(filename)
        print(f"Deleted {args.delete}" + (f" ({filename})" if filename else ""))
        return 0

    if args.paths:
        for path in args.paths:
            storage.save(path.name, path.read_bytes())
            print(f"Uploaded {path.name} -> {settings.document_storage} storage")
        names = [p.name for p in args.paths]
    else:
        names = storage.list()
    if not names:
        print(f"No PDFs given and none found in {settings.document_storage} storage", file=sys.stderr)
        return 1

    embedder = get_embedder(settings)
    for name in names:
        started = time.perf_counter()
        count = ingest_document(name, storage.read(name), embedder, store, settings)
        print(f"{name}: {count} chunks ({time.perf_counter() - started:.1f}s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
