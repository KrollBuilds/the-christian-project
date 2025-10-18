"""Optional utility to merge doctrinal and contextual FAISS indexes."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

import faiss
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.query_rag import (  # noqa: E402
    CONTEXT_INDEX_PATH,
    CONTEXT_METADATA_PATH,
    QA_INDEX_PATH,
    QA_METADATA_PATH,
)

OUTPUT_DIR = Path("data") / "processed" / "combined_embeddings"
OUTPUT_INDEX = OUTPUT_DIR / "combined_faiss.index"
OUTPUT_METADATA = OUTPUT_DIR / "combined_metadata.json"


def load_index_and_metadata(
    index_path: Path, metadata_path: Path, label: str
) -> Tuple[faiss.Index, List[dict]]:
    if not index_path.exists() or not metadata_path.exists():
        raise FileNotFoundError(f"Missing {label} index or metadata.")
    index = faiss.read_index(str(index_path))
    with metadata_path.open("r", encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)
    return index, metadata


def index_to_matrix(index: faiss.IndexFlatIP) -> np.ndarray:
    xb = faiss.vector_float_to_array(index.xb)
    return xb.reshape(index.ntotal, index.d)


def merge_indexes() -> None:
    qa_index, qa_meta = load_index_and_metadata(
        QA_INDEX_PATH, QA_METADATA_PATH, "doctrinal"
    )
    context_index, context_meta = load_index_and_metadata(
        CONTEXT_INDEX_PATH, CONTEXT_METADATA_PATH, "contextual"
    )

    embeddings = np.vstack(
        [
            index_to_matrix(qa_index),
            index_to_matrix(context_index),
        ]
    )

    new_index = faiss.IndexFlatIP(embeddings.shape[1])
    new_index.add(embeddings.astype("float32"))

    combined_metadata: List[Dict[str, object]] = []
    for entry in qa_meta:
        entry = dict(entry)
        entry["source_category"] = "doctrine"
        combined_metadata.append(entry)
    for entry in context_meta:
        entry = dict(entry)
        entry["source_category"] = "context"
        combined_metadata.append(entry)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    faiss.write_index(new_index, str(OUTPUT_INDEX))
    with OUTPUT_METADATA.open("w", encoding="utf-8") as metadata_file:
        json.dump(combined_metadata, metadata_file, ensure_ascii=True, indent=2)

    print(f"Combined index saved to {OUTPUT_INDEX}")
    print(f"Combined metadata saved to {OUTPUT_METADATA}")
    print(f"Total vectors: {new_index.ntotal}")


if __name__ == "__main__":
    merge_indexes()
