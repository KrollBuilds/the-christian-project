"""Privacy helpers for sanitizing user-provided text."""

from __future__ import annotations


def sanitize_text(text: object) -> str:
    """Remove obvious identifiers and limit length for safe logging."""
    if text is None:
        return ""
    value = str(text).replace("@", "[at]").strip()
    return value[:2000]
