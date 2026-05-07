"""Automatic training pipeline.

Auto-training mutates the contextual FAISS index and is therefore disabled by
default. Set AUTO_TRAIN_ENABLED=true to allow high-scoring responses to be
embedded directly into retrieval.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONTEXT_INDEX_PATH = PROJECT_ROOT / "data" / "processed" / "wels_embeddings" / "context_faiss.index"
CONTEXT_METADATA_PATH = PROJECT_ROOT / "data" / "processed" / "wels_embeddings" / "context_metadata.json"

# Mutating retrieval indexes from runtime feedback must be opt-in.
AUTO_TRAIN_ENABLED = os.getenv("AUTO_TRAIN_ENABLED", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}

# Configurable via env var; only used when AUTO_TRAIN_ENABLED is true.
AUTO_TRAIN_THRESHOLD = float(os.getenv("AUTO_TRAIN_THRESHOLD", "0.75"))
EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
EMBEDDING_DIM = 384  # all-MiniLM-L6-v2 output dimension


def maybe_auto_train(
    question: str,
    answer: str,
    tone_score: float,
    topic: str = "General",
) -> bool:
    """
    Embed and store a Q&A pair if its tone_score meets the threshold.

    Returns True if training occurred, False otherwise.
    Never raises — training failures are logged but must not break chat.
    """
    if not AUTO_TRAIN_ENABLED:
        return False

    if tone_score < AUTO_TRAIN_THRESHOLD:
        return False

    if not question.strip() or not answer.strip():
        return False

    try:
        _embed_and_store(question, answer, topic)
        logger.info(
            "Auto-trained Q&A (tone=%.2f, topic=%s): %.60s...",
            tone_score, topic, question,
        )
        return True
    except Exception as exc:
        logger.warning("Auto-training skipped (non-critical): %s", exc)
        return False


def _embed_and_store(question: str, answer: str, topic: str) -> None:
    """Embed a Q&A pair and add it to the contextual FAISS index."""
    import faiss
    import numpy as np
    from sentence_transformers import SentenceTransformer

    # Load embedding model (re-uses the same global cache in query_rag if imported)
    try:
        import scripts.query_rag as rag
        model = rag.get_embedding_model()
    except Exception:
        model = SentenceTransformer(EMBEDDING_MODEL_NAME)

    # Encode question + answer together for richer retrieval context
    text = f"Q: {question.strip()}\nA: {answer.strip()}"
    embedding = model.encode(
        [text],
        convert_to_numpy=True,
        normalize_embeddings=True,
    ).astype("float32")

    CONTEXT_INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)

    # Load existing index + metadata, or initialize new ones
    if CONTEXT_INDEX_PATH.exists() and CONTEXT_METADATA_PATH.exists():
        index = faiss.read_index(str(CONTEXT_INDEX_PATH))
        with CONTEXT_METADATA_PATH.open("r", encoding="utf-8") as f:
            metadata: list = json.load(f)
    else:
        index = faiss.IndexFlatIP(EMBEDDING_DIM)
        metadata = []

    index.add(embedding)
    metadata.append({
        "title": question.strip()[:100],
        "content": answer.strip(),
        "topic": topic,
        "source": "auto_trained",
        "auto_trained": True,
        "trained_at": datetime.now(timezone.utc).isoformat(),
        "type": "auto_qa",
    })

    # Persist updated index and metadata
    faiss.write_index(index, str(CONTEXT_INDEX_PATH))
    with CONTEXT_METADATA_PATH.open("w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)

    # Invalidate the in-memory cache so the next query loads the updated index
    _invalidate_context_cache()


def _invalidate_context_cache() -> None:
    """Clear the in-memory FAISS context cache in query_rag."""
    try:
        import scripts.query_rag as rag
        rag._CONTEXT_CACHE = None
    except Exception:
        pass
