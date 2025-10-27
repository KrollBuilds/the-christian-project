"""
Build FAISS embeddings for doctrinal and pastoral teaching content.

This pipeline:
    • Loads consolidated doctrine points (convert_wels_theology_auto.py output).
    • Loads curated pastoral teaching transcripts prepared via prepare_pastoral_teachings.py.
    • Chunks each entry with light overlap for smoother retrieval.
    • Preserves rich metadata (pastor, date, topic, source) alongside each chunk.
    • Saves a cosine-similarity FAISS index and metadata JSON for the chat experience.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# --- Paths ---
SOURCE_DATASETS: List[Tuple[str, Path]] = [
    ("doctrine", Path("data/processed/wels_doctrine.jsonl")),
    ("pastoral_teaching", Path("data/processed/pastoral_teachings.jsonl")),
]
OUTPUT_DIR = Path("data/processed/wels_embeddings")
INDEX_PATH = OUTPUT_DIR / "wels_faiss.index"
METADATA_PATH = OUTPUT_DIR / "wels_metadata.json"

MODEL_NAME = "all-MiniLM-L6-v2"
WORDS_PER_CHUNK_DEFAULT = 300
WORDS_PER_CHUNK_PASTORAL = 240
WORD_OVERLAP = 40


# ---------------------------------------------------------------------------

def load_records(paths: List[Tuple[str, Path]]) -> List[Dict[str, str]]:
    records: List[Dict[str, str]] = []
    counts: Counter[str] = Counter()
    for dataset_name, path in paths:
        if not path.exists():
            print(f"⚠️ Skipping missing dataset: {path}")
            continue
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if not rec.get("content"):
                    continue
                rec["_dataset"] = dataset_name
                records.append(rec)
                counts[dataset_name] += 1
    if not records:
        raise ValueError("No valid records found for embedding.")
    print(
        "Loaded source records:",
        ", ".join(f"{label}={counts[label]}" for label in sorted(counts)),
    )
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
    records = load_records(SOURCE_DATASETS)

    model = SentenceTransformer(MODEL_NAME)
    dim = model.get_sentence_embedding_dimension()
    index = faiss.IndexFlatIP(dim)

    texts: List[str] = []
    metadata: List[Dict[str, str]] = []
    chunk_count = 0

    for record in records:
        dataset = record.get("_dataset", record.get("type", "doctrine"))
        base_meta = {
            "id": record.get("id"),
            "title": record.get("title", ""),
            "point_number": record.get("point_number", ""),
            "source_file": record.get("source_file", record.get("source")),
            "source": record.get("source", ""),
            "scripture_refs": record.get("scripture_refs", []),
            "type": record.get("type", dataset),
            "dataset": dataset,
            "pastor": record.get("pastor") or record.get("speaker"),
            "event_date": record.get("event_date") or record.get("date"),
            "topic": record.get("topic") or record.get("series"),
            "tags": record.get("tags", []),
        }

        content = record.get("content", "")
        chunk_size = (
            WORDS_PER_CHUNK_PASTORAL
            if dataset == "pastoral_teaching"
            else WORDS_PER_CHUNK_DEFAULT
        )
        chunks = list(chunk_text(content, chunk_size, WORD_OVERLAP))

        for i, chunk in enumerate(chunks):
            chunk_count += 1
            header_parts = [f"Title: {base_meta['title']}", f"Type: {base_meta['type']}"]
            if base_meta.get("pastor"):
                header_parts.append(f"Pastor: {base_meta['pastor']}")
            if base_meta.get("event_date"):
                header_parts.append(f"Date: {base_meta['event_date']}")
            if base_meta.get("topic"):
                header_parts.append(f"Topic: {base_meta['topic']}")
            if base_meta.get("source"):
                header_parts.append(f"Source: {base_meta['source']}")
            header_parts.append(f"Content: {chunk}")
            texts.append("\n".join(part for part in header_parts if part))

            m = base_meta.copy()
            m["chunk_id"] = f"{base_meta['id']}#chunk-{i}"
            m["content"] = chunk
            m["chunk_index"] = i
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

    print(f"✅ Embedded {chunk_count} chunks from {len(records)} source entries.")
    print(f"FAISS index saved → {INDEX_PATH}")
    print(f"Metadata saved → {METADATA_PATH}")


if __name__ == "__main__":
    main()
