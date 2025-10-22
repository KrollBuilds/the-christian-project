"""
Utilities for querying doctrinal and contextual knowledge bases.
Auto-detects whether to use legacy QA index, combined index, or new WELS doctrinal index.
"""

from __future__ import annotations
import argparse
import json
import logging
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

# --- Project setup ---
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# ---------------------------------------------------------------------
# Utility fallbacks (so the file works standalone)
try:
    from app.auth_utils import get_current_user
except Exception:
    def get_current_user() -> str: return "guest"

try:
    from app.privacy_utils import sanitize_text
except Exception:
    def sanitize_text(text: object) -> str:
        if text is None: return ""
        return str(text).replace("@", "[at]").strip()[:2000]

try:
    from scripts.track_usage import record_usage
except Exception:
    def record_usage(*a, **kw): return None
# ---------------------------------------------------------------------

from config import SETTINGS
from config.prompt_templates import (
    FALLBACK_PROMPT, SYSTEM_PROMPT, SYNTHESIS_PROMPT_TEMPLATE
)
from config.settings import MAX_TOKENS, TEMPERATURE

os.environ["TOKENIZERS_PARALLELISM"] = "false"
logger = logging.getLogger(__name__)

# --- Legacy and new index locations ---
QA_VECTOR_DIR = PROJECT_ROOT / "data" / "processed" / "vector_store"
WELS_VECTOR_DIR = PROJECT_ROOT / "data" / "processed" / "wels_embeddings"

# Legacy
QA_INDEX_PATH = QA_VECTOR_DIR / "qa_faiss.index"
QA_METADATA_PATH = QA_VECTOR_DIR / "qa_metadata.json"
COMBINED_INDEX_PATH = QA_VECTOR_DIR / "combined_faiss.index"
COMBINED_METADATA_PATH = QA_VECTOR_DIR / "combined_metadata.json"
# New doctrinal embeddings
WELS_INDEX_PATH = WELS_VECTOR_DIR / "wels_faiss.index"
WELS_METADATA_PATH = WELS_VECTOR_DIR / "wels_metadata.json"
# Contextual (optional article data)
CONTEXT_INDEX_PATH = WELS_VECTOR_DIR / "context_faiss.index"
CONTEXT_METADATA_PATH = WELS_VECTOR_DIR / "context_metadata.json"

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_GPT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "generation_log.jsonl"

# ---------------------------------------------------------------------
# Index resolver
def _resolve_doctrine_paths() -> Tuple[Path, Path, str]:
    """Determine which doctrinal FAISS index to use."""
    if WELS_INDEX_PATH.exists() and WELS_METADATA_PATH.exists():
        logger.info("Using new WELS doctrinal index (wels_faiss.index).")
        return WELS_INDEX_PATH, WELS_METADATA_PATH, "wels"
    if COMBINED_INDEX_PATH.exists() and COMBINED_METADATA_PATH.exists():
        logger.info("Using combined doctrinal index (combined_faiss.index).")
        return COMBINED_INDEX_PATH, COMBINED_METADATA_PATH, "combined"
    if QA_INDEX_PATH.exists() and QA_METADATA_PATH.exists():
        logger.info("Using legacy QA doctrinal index (qa_faiss.index).")
        return QA_INDEX_PATH, QA_METADATA_PATH, "qa"
    raise FileNotFoundError("No doctrinal FAISS index found (wels / combined / qa).")

DOCTRINE_INDEX_PATH, DOCTRINE_METADATA_PATH, DOCTRINE_INDEX_LABEL = _resolve_doctrine_paths()

# ---------------------------------------------------------------------
# Cache containers
_QA_CACHE: Optional[Tuple[faiss.Index, List[dict]]] = None
_CONTEXT_CACHE: Optional[Tuple[Optional[faiss.Index], List[dict]]] = None
_MODEL_CACHE: Optional[SentenceTransformer] = None

# ---------------------------------------------------------------------
# Core load functions
def _load_index_and_metadata(index_path: Path, metadata_path: Path, label: str) -> Tuple[faiss.Index, List[dict]]:
    if not index_path.exists():
        raise FileNotFoundError(f"Missing {label} index at {index_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing {label} metadata at {metadata_path}")
    index = faiss.read_index(str(index_path))
    with metadata_path.open("r", encoding="utf-8") as f:
        metadata = json.load(f)
    if not isinstance(metadata, list) or not metadata:
        raise ValueError(f"{label.capitalize()} metadata is empty or malformed.")
    return index, metadata

def get_cached_doctrine_index() -> Tuple[faiss.Index, List[dict]]:
    global _QA_CACHE
    if _QA_CACHE is None:
        _QA_CACHE = _load_index_and_metadata(DOCTRINE_INDEX_PATH, DOCTRINE_METADATA_PATH, DOCTRINE_INDEX_LABEL)
    return _QA_CACHE

def get_cached_context_index() -> Tuple[Optional[faiss.Index], List[dict]]:
    global _CONTEXT_CACHE
    if _CONTEXT_CACHE is None:
        try:
            _CONTEXT_CACHE = _load_index_and_metadata(CONTEXT_INDEX_PATH, CONTEXT_METADATA_PATH, "contextual")
        except FileNotFoundError:
            logger.info("No contextual index found; skipping context retrieval.")
            _CONTEXT_CACHE = (None, [])
    return _CONTEXT_CACHE

def get_embedding_model() -> SentenceTransformer:
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        _MODEL_CACHE = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _MODEL_CACHE

# ---------------------------------------------------------------------
# Retrieval utilities
def retrieve_similar(query: str, model: SentenceTransformer, index: faiss.Index, top_k: int):
    query_emb = model.encode([query], convert_to_numpy=True, normalize_embeddings=True).astype("float32")
    scores, indices = index.search(query_emb, top_k)
    return scores[0], indices[0]

def _format_metadata_snippet(entry: Dict[str, object]) -> str:
    title = entry.get("title") or "Doctrinal Reference"
    content = entry.get("content", "")
    snippet = f"Title: {title}"
    if content:
        snippet += f"\nContent: {content}"
    if "scripture_refs" in entry and entry["scripture_refs"]:
        refs = ", ".join(entry["scripture_refs"])
        snippet += f"\nScripture Refs: {refs}"
    return snippet.strip()

def build_doctrinal_context(entries: List[Dict[str, object]]) -> str:
    if not entries: return "No doctrinal sources available."
    return "\n\n".join(_format_metadata_snippet(e) for e in entries)

def build_contextual_context(entries: List[Dict[str, object]]) -> str:
    if not entries: return "No contextual sources available."
    parts = []
    for e in entries:
        parts.append(f"Title: {e.get('title','')}\nType: {e.get('type','')}\nContent: {e.get('content','')}")
    return "\n\n".join(parts)

# ---------------------------------------------------------------------
# Main retrieval interfaces
def retrieve_doctrinal_sources(question: str, top_k: int = 3) -> List[Dict[str, object]]:
    index, metadata = get_cached_doctrine_index()
    model = get_embedding_model()
    scores, idxs = retrieve_similar(question, model, index, top_k)
    results: List[Dict[str, object]] = []
    for score, i in zip(scores, idxs):
        if i < 0 or i >= len(metadata): continue
        entry = metadata[i].copy()
        entry["score"] = float(score)
        entry["source_category"] = "doctrine"
        entry["vector_source"] = DOCTRINE_INDEX_LABEL
        results.append(entry)
    return results

def retrieve_contextual_sources(question: str, top_k: int = 2) -> List[Dict[str, object]]:
    index, metadata = get_cached_context_index()
    if index is None or not metadata: return []
    model = get_embedding_model()
    scores, idxs = retrieve_similar(question, model, index, top_k)
    results = []
    for s, i in zip(scores, idxs):
        if i < 0 or i >= len(metadata): continue
        e = metadata[i].copy()
        e["score"] = float(s)
        e["source_category"] = "context"
        results.append(e)
    return results

# ---------------------------------------------------------------------
# (Remaining synthesis + CLI code unchanged from your version)
# Keep run_gpt_synthesis, evaluate_tone, sanitize_output, log_generation,
# query_with_gpt, and main() as-is.
