"""Utilities for managing training data and review workflow."""

import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Any

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
APPROVED_FILE = PROJECT_ROOT / "data" / "metrics" / "approved_training.jsonl"
REVIEW_QUEUE_FILE = PROJECT_ROOT / "data" / "metrics" / "review_queue.jsonl"

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


def update_review_queue_topic(response_id: str, new_topic: str) -> bool:
    """
    Update the topic for a specific response in the review queue.

    Args:
        response_id: Unique identifier for the response
        new_topic: New topic classification

    Returns:
        True if update was successful, False otherwise
    """
    if not REVIEW_QUEUE_FILE.exists():
        print(f"⚠️ Review queue file not found: {REVIEW_QUEUE_FILE}")
        return False

    # Read all entries
    entries = []
    updated = False

    try:
        with REVIEW_QUEUE_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entry = json.loads(line)
                    # Update topic if this is the matching entry
                    if entry.get("response_id") == response_id:
                        entry["topic_cluster"] = new_topic
                        updated = True
                        print(f"🔄 Updated topic for {response_id}: {new_topic}")
                    entries.append(entry)

        # Write back all entries if update occurred
        if updated:
            with REVIEW_QUEUE_FILE.open("w", encoding="utf-8") as f:
                for entry in entries:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            print(f"✅ Review queue updated successfully")
            return True
        else:
            print(f"⚠️ Response ID {response_id} not found in review queue")
            return False

    except Exception as e:
        print(f"❌ Error updating review queue: {e}")
        return False
