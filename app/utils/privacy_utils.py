"""Utilities for sanitizing personally identifiable information (PII)."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Iterable, List, Tuple

import spacy
from spacy.language import Language
from spacy.tokens import Span

ALLOWED_LABELS = {"PERSON", "ORG", "GPE", "LOC", "EMAIL", "PHONE_NUMBER"}
EMAIL_REGEX = re.compile(r"[\w\.-]+@[\w\.-]+\.[a-zA-Z]{2,}")
PHONE_REGEX = re.compile(r"(?:\+?\d[\d\-\s]{7,}\d)")
PERSON_REGEX = re.compile(r"\b([A-Z][a-z]+(?:\s+[A-Z][a-z]+)+)\b")


@lru_cache(maxsize=1)
def _load_nlp() -> Language:
    """
    Load a spaCy pipeline, preferring the small English core model.

    Falls back to a blank English pipeline with basic entity rules when the
    pre-trained model is unavailable (e.g., in offline environments).
    """
    try:
        return spacy.load("en_core_web_sm")
    except OSError:
        nlp = spacy.blank("en")
        ruler = nlp.add_pipe("entity_ruler")
        ruler.add_patterns(
            [
                {"label": "EMAIL", "pattern": [{"TEXT": {"REGEX": EMAIL_REGEX.pattern}}]},
                {"label": "PHONE_NUMBER", "pattern": [{"TEXT": {"REGEX": PHONE_REGEX.pattern}}]},
            ]
        )
        return nlp


def _collect_spacy_spans(text: str) -> Iterable[Span]:
    doc = _load_nlp()(text)
    for ent in doc.ents:
        if ent.label_ in ALLOWED_LABELS:
            yield ent


def _collect_regex_spans(text: str) -> List[Tuple[int, int, str, str]]:
    spans = []
    for match in EMAIL_REGEX.finditer(text):
        spans.append((match.start(), match.end(), "EMAIL", match.group()))
    for match in PHONE_REGEX.finditer(text):
        spans.append((match.start(), match.end(), "PHONE_NUMBER", match.group()))
    for match in PERSON_REGEX.finditer(text):
        spans.append((match.start(), match.end(), "PERSON", match.group()))
    return spans


def _merge_spans(text: str, spans: Iterable[Tuple[int, int, str, str]]) -> Tuple[str, List[Tuple[str, str]]]:
    sorted_spans = sorted(spans, key=lambda item: (item[0], -(item[1] - item[0])))
    sanitized_parts: List[str] = []
    detected: List[Tuple[str, str]] = []
    cursor = 0

    for start, end, label, original in sorted_spans:
        if start < cursor:
            continue
        sanitized_parts.append(text[cursor:start])
        sanitized_parts.append(f"[{label}]")
        detected.append((label, original))
        cursor = end

    sanitized_parts.append(text[cursor:])
    return "".join(sanitized_parts), detected


def redact_pii(text: str) -> Tuple[str, List[Tuple[str, str]]]:
    """
    Detect and replace personally identifiable information with labeled tokens.

    Args:
        text: Input text that may contain PII.

    Returns:
        sanitized_text: The text with entities replaced.
        detected_entities: List of (label, entity_text) tuples describing what was removed.
    """
    spacy_spans = [(ent.start_char, ent.end_char, ent.label_, ent.text) for ent in _collect_spacy_spans(text)]
    regex_spans = _collect_regex_spans(text)

    # Combine and deduplicate spans with preference to spaCy detections.
    seen_positions = set()
    all_spans = []
    for span in spacy_spans + regex_spans:
        key = (span[0], span[1])
        if key in seen_positions:
            continue
        seen_positions.add(key)
        all_spans.append(span)

    return _merge_spans(text, all_spans)
