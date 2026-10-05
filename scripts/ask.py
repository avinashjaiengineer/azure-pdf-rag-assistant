"""Ask questions against the indexed PDFs.

Usage:
    python -m scripts.ask "What is AKS?"
    python -m scripts.ask              # interactive mode
    python -m scripts.ask -v "..."     # also print retrieved chunks and scores
"""

import argparse
import sys

from src.models.schemas import Answer
from src.rag.pipeline import build_pipeline


def print_answer(answer: Answer, verbose: bool) -> None:
    print(f"\n{answer.answer}\n")
    if answer.citations:
        print("Sources:")
        for c in answer.citations:
            print(f"  - {c.filename}, page {c.page_number}")
    if verbose:
        print("\nRetrieved chunks:")
        for r in answer.sources:
            preview = r.chunk.content[:160].replace("\n", " ")
            print(f"  [{r.score:.4f}] {r.chunk.filename} p{r.chunk.page_number}: {preview}...")
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("question", nargs="?")
    parser.add_argument("-k", "--top-k", type=int)
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    pipeline = build_pipeline()

    if args.question:
        print_answer(pipeline.ask(args.question, args.top_k), args.verbose)
        return 0

    print("Ask a question (empty line to quit).")
    while question := input("> ").strip():
        print_answer(pipeline.ask(question, args.top_k), args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main())
