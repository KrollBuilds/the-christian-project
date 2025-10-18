"""Utilities for querying doctrinal and contextual knowledge bases."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

try:
    from app.auth_utils import get_current_user
except Exception:  # pragma: no cover - fallback for CLI usage
    def get_current_user() -> str:
        return "guest"

try:
    from app.privacy_utils import sanitize_text
except Exception:  # pragma: no cover - fallback for CLI usage
    def sanitize_text(text: object) -> str:
        if text is None:
            return ""
        return str(text).replace("@", "[at]").strip()[:2000]

try:
    from scripts.track_usage import record_usage
except Exception:  # pragma: no cover - fallback when metrics disabled
    def record_usage(*args, **kwargs) -> None:
        return None

from config import SETTINGS
from config.prompt_templates import (
    FALLBACK_PROMPT,
    SYSTEM_PROMPT,
    SYNTHESIS_PROMPT_TEMPLATE,
)
from config.settings import MAX_TOKENS, TEMPERATURE

os.environ["TOKENIZERS_PARALLELISM"] = "false"

QA_VECTOR_DIR = PROJECT_ROOT / "data" / "processed" / "vector_store"
QA_INDEX_PATH = QA_VECTOR_DIR / "qa_faiss.index"
QA_METADATA_PATH = QA_VECTOR_DIR / "qa_metadata.json"

CONTEXT_VECTOR_DIR = PROJECT_ROOT / "data" / "processed" / "wels_embeddings"
CONTEXT_INDEX_PATH = CONTEXT_VECTOR_DIR / "context_faiss.index"
CONTEXT_METADATA_PATH = CONTEXT_VECTOR_DIR / "context_metadata.json"

EMBEDDING_MODEL_NAME = "all-MiniLM-L6-v2"
DEFAULT_GPT_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

_QA_CACHE: Optional[Tuple[faiss.Index, List[dict]]] = None
_CONTEXT_CACHE: Optional[Tuple[faiss.Index, List[dict]]] = None
_MODEL_CACHE: Optional[SentenceTransformer] = None

LOG_DIR = PROJECT_ROOT / "logs"
LOG_FILE = LOG_DIR / "generation_log.jsonl"


def _load_index_and_metadata(
    index_path: Path, metadata_path: Path, label: str
) -> Tuple[faiss.Index, List[dict]]:
    if not index_path.exists():
        raise FileNotFoundError(f"Missing {label} index at {index_path}")
    if not metadata_path.exists():
        raise FileNotFoundError(f"Missing {label} metadata at {metadata_path}")

    index = faiss.read_index(str(index_path))
    with metadata_path.open("r", encoding="utf-8") as metadata_file:
        metadata = json.load(metadata_file)

    if not isinstance(metadata, list) or not metadata:
        raise ValueError(f"{label.capitalize()} metadata is empty or malformed.")

    return index, metadata


def get_cached_doctrine_index() -> Tuple[faiss.Index, List[dict]]:
    global _QA_CACHE
    if _QA_CACHE is None:
        _QA_CACHE = _load_index_and_metadata(
            QA_INDEX_PATH, QA_METADATA_PATH, "doctrinal"
        )
    return _QA_CACHE


def get_cached_context_index() -> Tuple[faiss.Index, List[dict]]:
    global _CONTEXT_CACHE
    if _CONTEXT_CACHE is None:
        _CONTEXT_CACHE = _load_index_and_metadata(
            CONTEXT_INDEX_PATH, CONTEXT_METADATA_PATH, "contextual"
        )
    return _CONTEXT_CACHE


def get_embedding_model() -> SentenceTransformer:
    global _MODEL_CACHE
    if _MODEL_CACHE is None:
        _MODEL_CACHE = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _MODEL_CACHE


def retrieve_similar(
    query: str,
    model: SentenceTransformer,
    index: faiss.Index,
    top_k: int,
) -> Tuple[np.ndarray, np.ndarray]:
    query_embedding = model.encode(
        [query], convert_to_numpy=True, normalize_embeddings=True
    ).astype("float32")
    scores, indices = index.search(query_embedding, top_k)
    return scores[0], indices[0]


def format_truncated_answer(answer: str, limit: int = 400) -> str:
    if len(answer) <= limit:
        return answer
    return answer[: limit - 3] + "..."


def build_doctrinal_context(entries: List[Dict[str, object]]) -> str:
    if not entries:
        return "No doctrinal sources available."
    parts = []
    for entry in entries:
        question = entry.get("question", "")
        answer = entry.get("answer", "")
        parts.append(f"Question: {question}\nAnswer: {answer}")
    return "\n\n".join(parts)


def build_contextual_context(entries: List[Dict[str, object]]) -> str:
    if not entries:
        return "No contextual sources available."
    parts = []
    for entry in entries:
        title = entry.get("title", "")
        content = entry.get("content", "")
        source_type = entry.get("type", "")
        url = entry.get("url", "")
        url_fragment = f"\nURL: {url}" if url else ""
        parts.append(
            f"Title: {title}\nType: {source_type}\nContent: {content}{url_fragment}"
        )
    return "\n\n".join(parts)


def sanitize_output(text: str, width: int = 90) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"\[\d+\]", "", text)
    cleaned = re.sub(r"https?://\S+", "", cleaned)
    cleaned = cleaned.strip()
    if not cleaned:
        return ""
    paragraphs = []
    for paragraph in cleaned.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        paragraphs.append(textwrap.fill(paragraph, width=width))
    result = "\n\n".join(paragraphs).strip()
    if result and result[-1] not in ".!?":
        result += "."
    return result


def evaluate_tone(answer: str) -> float:
    if not answer:
        return 0.0
    lower = answer.lower()
    keywords = ["grace", "faith", "christ", "scripture", "gospel", "cross"]
    keyword_hits = sum(1 for keyword in keywords if keyword in lower)
    keyword_score = keyword_hits / len(keywords)

    word_count = len(answer.split())
    length_score = 1.0 if word_count <= 230 else 0.7 if word_count <= 350 else 0.5

    scripture_ref_score = 1.0 if re.search(r"\b[a-z]+\s+\d+:\d+", lower) else 0.6

    score = (keyword_score + length_score + scripture_ref_score) / 3
    return round(min(max(score, 0.0), 1.0), 3)


def log_generation(
    question: str,
    answer: str,
    tone_score: float,
    warnings: Optional[List[str]] = None,
) -> None:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "question": sanitize_text(question),
        "answer": sanitize_text(answer),
        "tone_score": tone_score,
        "warnings": warnings or [],
        "user_id": get_current_user(),
    }
    with LOG_FILE.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_entry, ensure_ascii=True) + "\n")


def retrieve_doctrinal_sources(question: str, top_k: int = 3) -> List[Dict[str, object]]:
    index, metadata = get_cached_doctrine_index()
    model = get_embedding_model()
    scores, indices = retrieve_similar(question, model, index, top_k=top_k)

    results: List[Dict[str, object]] = []
    for score, idx in zip(scores, indices):
        if idx < 0 or idx >= len(metadata):
            continue
        entry = metadata[idx].copy()
        entry["score"] = float(score)
        entry["source_category"] = "doctrine"
        results.append(entry)
    return results


def retrieve_contextual_sources(question: str, top_k: int = 2) -> List[Dict[str, object]]:
    index, metadata = get_cached_context_index()
    model = get_embedding_model()
    scores, indices = retrieve_similar(question, model, index, top_k=top_k)

    results: List[Dict[str, object]] = []
    for score, idx in zip(scores, indices):
        if idx < 0 or idx >= len(metadata):
            continue
        entry = metadata[idx].copy()
        entry["score"] = float(score)
        entry["source_category"] = "context"
        results.append(entry)
    return results


def run_gpt_synthesis(
    question: str,
    doctrine_entries: List[Dict[str, object]],
    contextual_entries: List[Dict[str, object]],
    model_name: str = DEFAULT_GPT_MODEL,
) -> str:
    if not doctrine_entries and not contextual_entries:
        return sanitize_output(FALLBACK_PROMPT)

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "OPENAI_API_KEY not found. Skipping GPT synthesis."

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        return "The 'openai' package is not installed; install it to enable GPT synthesis."

    # Instantiate client (explicit api_key for clarity, with fallback)
    try:
        client = OpenAI(api_key=api_key)
    except Exception:
        client = OpenAI()

    doctrinal_context = build_doctrinal_context(doctrine_entries)
    contextual_context = build_contextual_context(contextual_entries)

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": SYNTHESIS_PROMPT_TEMPLATE.format(
                doctrinal_context=doctrinal_context,
                contextual_context=contextual_context,
                user_question=question,
            ),
        },
    ]

    try:
        response = client.chat.completions.create(
            model=model_name,
            temperature=TEMPERATURE,
            max_tokens=MAX_TOKENS,
            messages=messages,
        )
    except Exception as exc:
        return f"OpenAI API error: {exc}"

    usage = getattr(response, "usage", None)
    if usage is not None and SETTINGS.get("usage_logging", True):
        prompt_tokens = getattr(usage, "prompt_tokens", 0) or 0
        completion_tokens = getattr(usage, "completion_tokens", 0) or 0
        try:
            record_usage(int(prompt_tokens), int(completion_tokens), model=model_name)
        except Exception:
            pass

    if not getattr(response, "choices", None):
        return "OpenAI API returned no choices."

    first_choice = response.choices[0]
    content = getattr(getattr(first_choice, "message", None), "content", None) or getattr(
        first_choice, "text", ""
    )
    return sanitize_output(content)


def query_with_gpt(
    question: str,
    *,
    doctrine_top_k: int = 3,
    context_top_k: int = 2,
    model_name: str = DEFAULT_GPT_MODEL,
    doctrine_entries: Optional[List[Dict[str, object]]] = None,
    contextual_entries: Optional[List[Dict[str, object]]] = None,
) -> Dict[str, object]:
    warnings: List[str] = []
    if doctrine_entries is None:
        doctrine_entries = retrieve_doctrinal_sources(question, top_k=doctrine_top_k)

    if contextual_entries is None:
        try:
            contextual_entries = retrieve_contextual_sources(
                question, top_k=context_top_k
            )
        except (FileNotFoundError, ValueError) as exc:
            contextual_entries = []
            warnings.append(
                f"Contextual sources unavailable. Using core doctrine only. ({exc})"
            )

    if not doctrine_entries and not contextual_entries:
        warnings.append(
            "No doctrinal or contextual sources retrieved; providing fallback guidance."
        )
        answer = sanitize_output(FALLBACK_PROMPT)
    else:
        answer = run_gpt_synthesis(
            question, doctrine_entries, contextual_entries, model_name=model_name
        )

    tone_score = evaluate_tone(answer)
    log_generation(question, answer, tone_score, warnings)

    return {
        "answer": answer,
        "doctrine": doctrine_entries,
        "contextual": contextual_entries,
        "warnings": warnings,
        "tone_score": tone_score,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Query the Christian Project knowledge bases."
    )
    parser.add_argument(
        "--gpt",
        action="store_true",
        help="Synthesize an answer with OpenAI after retrieval.",
    )
    args = parser.parse_args()

    question = input("Ask a theological question: ").strip()
    if not question:
        print("Empty question. Exiting.")
        return

    try:
        doctrine_matches = retrieve_doctrinal_sources(question, top_k=3)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Setup error: {exc}")
        return

    print("\nTop doctrinal answers:")
    for rank, entry in enumerate(doctrine_matches, start=1):
        question_text = entry.get("question", "N/A")
        answer = entry.get("answer", "")
        score = entry.get("score", 0.0)
        print(f"{rank}. (score {score:.2f}) Question: {question_text}")
        print(f"   Answer preview: {format_truncated_answer(answer)}")

    try:
        contextual_matches = retrieve_contextual_sources(question, top_k=2)
    except (FileNotFoundError, ValueError) as exc:
        contextual_matches = []
        print(f"\nContextual sources unavailable. Using core doctrine only. ({exc})")

    if contextual_matches:
        print("\nTop contextual articles:")
        for rank, entry in enumerate(contextual_matches, start=1):
            title = entry.get("title", "N/A")
            score = entry.get("score", 0.0)
            url = entry.get("url", "N/A")
            preview = entry.get("content", "")
            print(f"{rank}. (score {score:.2f}) Title: {title}")
            print(f"   URL: {url}")
            print(f"   Preview: {format_truncated_answer(preview)}")

    if args.gpt:
        print("\nRequesting synthesized answer from OpenAI...")
        result = query_with_gpt(
            question,
            doctrine_entries=doctrine_matches,
            contextual_entries=contextual_matches if contextual_matches else None,
        )
        for warning in result.get("warnings", []):
            print(f"Warning: {warning}")
        print("\nSynthesized Answer:")
        print(result.get("answer"))
        tone_score = result.get("tone_score")
        if tone_score is not None:
            print(f"\nTone score: {tone_score}")


if __name__ == "__main__":
    main()
