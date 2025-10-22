"""
Build FAISS embeddings for unified WELS doctrinal content
(from whatwebelive.txt + doctrine.txt merged in convert_wels_theology_auto.py).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, List

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# --- Paths ---
RAW_CONTENT_PATH = Path("data/processed/wels_doctrine.jsonl")
OUTPUT_DIR = Path("data/processed/wels_embeddings")
INDEX_PATH = OUTPUT_DIR / "wels_faiss.index"
METADATA_PATH = OUTPUT_DIR / "wels_metadata.json"

MODEL_NAME = "all-MiniLM-L6-v2"
WORDS_PER_CHUNK = 300   # smaller chunk size fits short doctrinal points better
WORD_OVERLAP = 40


# ---------------------------------------------------------------------------

def load_records(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Expected dataset at {path}")
    records: List[Dict[str, str]] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                if rec.get("content"):
                    records.append(rec)
            except json.JSONDecodeError:
                continue
    if not records:
        raise ValueError(f"No valid records found in {path}")
    return records


def chunk_text(text: str, words_per_chunk: int, overlap: int) -> Iterable[str]:
    words = text.split()
    if not words:
        return []
    start = 0
    total = len(words)
    while start < total:
        end = min(start + words_per_chunk, total)
        yield " ".join(words[start:end])
        if end == total:
            break
        start = max(end - overlap, start + 1)


# ---------------------------------------------------------------------------

def main() -> None:
    records = load_records(RAW_CONTENT_PATH)

    model = SentenceTransformer(MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    index = faiss.IndexFlatIP(dim)

    texts: List[str] = []
    metadata: List[Dict[str, str]] = []
    chunk_count = 0

    for record in records:
        base_meta = {
            "id": record.get("id"),
            "title": record.get("title", ""),
            "point_number": record.get("point_number", ""),
            "source_file": record.get("source_file", ""),
            "scripture_refs": record.get("scripture_refs", []),
            "type": record.get("type", ""),
        }

        content = record.get("content", "")
        chunks = list(chunk_text(content, WORDS_PER_CHUNK, WORD_OVERLAP))

        for i, chunk in enumerate(chunks):
            chunk_count += 1
            texts.append(
                f"Title: {base_meta['title']}\nType: {base_meta['type']}\nContent: {chunk}"
            )
            m = base_meta.copy()
            m["chunk_id"] = f"{base_meta['id']}#chunk-{i}"
            m["content"] = chunk
            metadata.append(m)

    if not texts:
        raise ValueError("No text chunks produced for embedding.")

    embeddings = model.encode(
        texts, convert_to_numpy=True, normalize_embeddings=True
    ).astype("float32")
    index.add(embeddings)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(index, str(INDEX_PATH))
    with METADATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    print(f"✅ Embedded {chunk_count} chunks from {len(records)} doctrinal entries.")
    print(f"FAISS index saved → {INDEX_PATH}")
    print(f"Metadata saved → {METADATA_PATH}")


if __name__ == "__main__":
    main()
