"""Build FAISS embeddings for contextual WELS articles."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

RAW_CONTENT_PATH = Path("data") / "raw" / "wels_articles" / "wels_content.jsonl"
OUTPUT_DIR = Path("data") / "processed" / "wels_embeddings"
INDEX_PATH = OUTPUT_DIR / "context_faiss.index"
METADATA_PATH = OUTPUT_DIR / "context_metadata.json"
MODEL_NAME = "all-MiniLM-L6-v2"
WORDS_PER_CHUNK = 400
WORD_OVERLAP = 50


def load_records(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Expected scraped content at {path}")

    records: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not records:
        raise ValueError(f"No valid records in {path}")
    return records


def chunk_text(text: str, words_per_chunk: int, overlap: int) -> Iterable[str]:
    words = text.split()
    if not words:
        return []

    start = 0
    total_words = len(words)
    while start < total_words:
        end = min(start + words_per_chunk, total_words)
        yield " ".join(words[start:end])
        if end == total_words:
            break
        start = max(end - overlap, start + 1)


def main() -> None:
    records = load_records(RAW_CONTENT_PATH)

    model = SentenceTransformer(MODEL_NAME)
    embedding_dim = model.get_sentence_embedding_dimension()
    index = faiss.IndexFlatIP(embedding_dim)

    texts: List[str] = []
    metadata: List[Dict[str, str]] = []

    chunk_count = 0
    for record in records:
        base_meta = {
            "title": record.get("title", ""),
            "url": record.get("url", ""),
            "type": record.get("type", ""),
        }
        chunks = list(
            chunk_text(record.get("content", ""), WORDS_PER_CHUNK, WORD_OVERLAP)
        )
        for i, chunk in enumerate(chunks):
            chunk_count += 1
            texts.append(
                f"Title: {base_meta['title']}\nType: {base_meta['type']}\nContent: {chunk}"
            )
            chunk_meta = base_meta.copy()
            chunk_meta["chunk_id"] = f"{base_meta['url']}#chunk-{i}"
            chunk_meta["content"] = chunk
            metadata.append(chunk_meta)

    if not texts:
        raise ValueError("No chunks generated for embedding.")

    embeddings = model.encode(
        texts, convert_to_numpy=True, normalize_embeddings=True
    ).astype("float32")
    index.add(embeddings)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    with METADATA_PATH.open("w", encoding="utf-8") as metadata_file:
        json.dump(metadata, metadata_file, ensure_ascii=True, indent=2)

    print(f"Embedded {chunk_count} chunks from {len(records)} articles.")
    print(f"FAISS index saved to {INDEX_PATH}")
    print(f"Metadata saved to {METADATA_PATH}")


if __name__ == "__main__":
    main()
