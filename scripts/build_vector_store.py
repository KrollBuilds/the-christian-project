"""Build a FAISS vector store from processed Q&A and doctrine datasets."""

from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Iterable, List

import faiss
from sentence_transformers import SentenceTransformer

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROCESSED_JSONL_PATH = PROJECT_ROOT / "data" / "processed" / "qa_clean.jsonl"
DOCTRINE_JSONL_PATH = PROJECT_ROOT / "data" / "processed" / "wels_doctrine.jsonl"
VECTOR_STORE_DIR = PROJECT_ROOT / "data" / "processed" / "vector_store"
INDEX_PATH = VECTOR_STORE_DIR / "combined_faiss.index"
METADATA_PATH = VECTOR_STORE_DIR / "combined_metadata.json"
LEGACY_INDEX_PATH = VECTOR_STORE_DIR / "qa_faiss.index"
LEGACY_METADATA_PATH = VECTOR_STORE_DIR / "qa_metadata.json"


def load_records(jsonl_path: Path) -> List[dict]:
    """Load cleaned Q&A records from the JSONL file."""
    if not jsonl_path.exists():
        raise FileNotFoundError(f"Expected JSONL at {jsonl_path}")

    records: List[dict] = []
    with jsonl_path.open("r", encoding="utf-8") as jsonl_file:
        for line in jsonl_file:
            line = line.strip()
            if not line:
                continue
            records.append(json.loads(line))

    if not records:
        raise ValueError(f"No records found in {jsonl_path}")

    return records


def batched(iterable: Iterable[str], batch_size: int) -> Iterable[List[str]]:
    """Yield lists of size batch_size from an iterable."""
    batch: List[str] = []
    for item in iterable:
        batch.append(item)
        if len(batch) == batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a FAISS vector store from processed datasets."
    )
    parser.add_argument(
        "--datasets",
        nargs="+",
        default=["qa", "doctrine"],
        help="Datasets to include: qa, doctrine, or both.",
    )
    return parser.parse_args()


def create_legacy_alias(target: Path, alias: Path) -> None:
    """Create a symlink (or copy fallback) so legacy paths remain available."""
    if alias.exists() or alias.is_symlink():
        alias.unlink()
    try:
        relative_target = target.name if alias.parent == target.parent else target
        alias.symlink_to(relative_target)
    except OSError:
        shutil.copy2(target, alias)


def main() -> None:
    args = parse_args()

    dataset_map = {
        "qa": PROCESSED_JSONL_PATH,
        "doctrine": DOCTRINE_JSONL_PATH,
    }

    selected = {name.lower() for name in args.datasets}
    unknown = selected - dataset_map.keys()
    if unknown:
        raise ValueError(f"Unknown dataset(s) requested: {', '.join(sorted(unknown))}")

    records: List[dict] = []
    for key, path in dataset_map.items():
        if key not in selected:
            print(f"Skipping dataset '{key}' (not requested).")
            continue

        if not path.exists():
            print(f"⚠️ Skipping missing file: {path}")
            continue

        print(f"Loading dataset: {path.name}")
        try:
            loaded = load_records(path)
        except ValueError as exc:
            print(f"⚠️ {exc}; skipping.")
            continue
        records.extend(loaded)

    if not records:
        raise ValueError("No data sources found for embedding.")

    qa_count = sum(1 for record in records if "question" in record and "answer" in record)
    doctrine_count = sum(
        1 for record in records if "content" in record and "question" not in record
    )
    print(
        f"Loaded {len(records)} total records "
        f"({qa_count} Q&A, {doctrine_count} doctrine/articles)."
    )

    # Prepare text chunks and the metadata we want to preserve.
    texts: List[str] = []
    metadata: List[dict] = []
    for record in records:
        if "question" in record and "answer" in record:
            text = f"Question: {record['question']}\nAnswer: {record['answer']}"
            section_type = "qa"
        elif "title" in record and "content" in record:
            text = f"Title: {record['title']}\nContent: {record['content']}"
            section_type = record.get("type", "doctrine")
        else:
            continue

        texts.append(text)
        metadata.append(
            {
                "id": record.get("id"),
                "type": section_type,
                "title": record.get("title"),
                "question": record.get("question"),
                "answer": record.get("answer"),
                "content": record.get("content"),
                "created": record.get("created"),
                "modified": record.get("modified"),
            }
        )

    if not texts:
        raise ValueError("No valid entries found for embedding.")

    total_records = len(texts)
    print(f"Preparing to embed {total_records} records.")

    # Create the embedding model once so we can reuse it for queries later.
    model = SentenceTransformer("all-MiniLM-L6-v2")
    embedding_dim = model.get_sentence_embedding_dimension()

    # Initialize a cosine-similarity FAISS index.
    index = faiss.IndexFlatIP(embedding_dim)

    # Encode in batches and add embeddings to FAISS, printing progress every 100 items.
    batch_size = 64
    processed = 0
    for batch_texts in batched(texts, batch_size):
        batch_embeddings = model.encode(
            batch_texts,
            convert_to_numpy=True,
            normalize_embeddings=True,
        )
        index.add(batch_embeddings.astype("float32"))
        processed += len(batch_texts)
        if processed % 100 == 0 or processed == total_records:
            print(f"Embedded {processed} / {total_records} records.")

    print(f"Finished indexing {processed} records.")

    # Persist the FAISS index and the metadata mapping for later retrieval.
    VECTOR_STORE_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    with METADATA_PATH.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, ensure_ascii=True, indent=2)
    create_legacy_alias(INDEX_PATH, LEGACY_INDEX_PATH)
    create_legacy_alias(METADATA_PATH, LEGACY_METADATA_PATH)

    print(f"Saved FAISS index to {INDEX_PATH}")
    print(f"Saved metadata to {METADATA_PATH}")

    # Simple interactive test: prompt for a question and show the top 3 matches.
    try:
        user_question = input("\nTest query (press Enter to skip): ").strip()
    except EOFError:
        user_question = ""

    if user_question:
        query_embedding = model.encode(
            [user_question],
            convert_to_numpy=True,
            normalize_embeddings=True,
        ).astype("float32")

        scores, indices = index.search(query_embedding, 3)
        print("\nTop matches:")
        for rank, (score, idx) in enumerate(zip(scores[0], indices[0]), start=1):
            if idx < 0 or idx >= len(metadata):
                continue
            result = metadata[idx]
            print(
                f"{rank}. Score {score:.4f} | Type: {result.get('type')} | "
                f"Title/Question: {result.get('title') or result.get('question')}"
            )
    else:
        print("Skipping interactive test.")


if __name__ == "__main__":
    main()
