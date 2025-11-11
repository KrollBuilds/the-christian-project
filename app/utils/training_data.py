"""Utilities for managing training data and review workflow."""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
APPROVED_FILE = PROJECT_ROOT / "data" / "metrics" / "approved_training.jsonl"

def save_approved_question(question: str, response: str, topic: str,
                           response_id: str, editor_notes: str = "") -> None:
    """
    Save an approved Q&A pair to training dataset.

    Args:
        question: The user's question
        response: The approved response (possibly edited)
        topic: Topic classification
        response_id: Unique identifier
        editor_notes: Optional notes from pastor
    """

    # Ensure directory exists
    APPROVED_FILE.parent.mkdir(parents=True, exist_ok=True)

    approved_entry = {
        "question": question,
        "response": response,
        "topic": topic,
        "response_id": response_id,
        "approved_at": datetime.utcnow().isoformat(),
        "editor_notes": editor_notes,
        "status": "approved"
    }

    # Append to approved training file
    with APPROVED_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(approved_entry, ensure_ascii=False) + "\n")

    print(f"✅ Approved Q&A saved to training: {response_id}")
