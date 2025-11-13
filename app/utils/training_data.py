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
                           response_id: str, editor_notes: str = "") -> Dict[str, Any]:
    """
    Save an approved Q&A pair to training dataset.

    Args:
        question: The user's question
        response: The approved response (possibly edited)
        topic: Topic classification
        response_id: Unique identifier
        editor_notes: Optional notes from pastor

    Returns:
        Dict with 'success' (bool), 'message' (str), and 'file_path' (str)
    """
    try:
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

        # Verify the file was written by checking it exists and has content
        if not APPROVED_FILE.exists():
            return {
                "success": False,
                "message": f"File was not created: {APPROVED_FILE}",
                "file_path": str(APPROVED_FILE)
            }

        file_size = APPROVED_FILE.stat().st_size
        print(f"✅ Approved Q&A saved to training: {response_id}")
        print(f"📁 File location: {APPROVED_FILE}")
        print(f"📊 File size: {file_size} bytes")

        return {
            "success": True,
            "message": f"Successfully saved to {APPROVED_FILE.name}",
            "file_path": str(APPROVED_FILE),
            "file_size": file_size,
            "response_id": response_id
        }

    except PermissionError as e:
        error_msg = f"Permission denied writing to {APPROVED_FILE}: {e}"
        print(f"❌ {error_msg}")
        return {
            "success": False,
            "message": error_msg,
            "file_path": str(APPROVED_FILE)
        }
    except Exception as e:
        error_msg = f"Error saving approved question: {e}"
        print(f"❌ {error_msg}")
        return {
            "success": False,
            "message": error_msg,
            "file_path": str(APPROVED_FILE)
        }


def get_recent_approved_entries(limit: int = 10) -> list[Dict[str, Any]]:
    """
    Get the most recent approved training entries.

    Args:
        limit: Maximum number of entries to return (default 10)

    Returns:
        List of approved entry dictionaries, most recent first
    """
    if not APPROVED_FILE.exists():
        return []

    try:
        entries = []
        with APPROVED_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))

        # Return most recent entries (last N lines)
        return entries[-limit:] if len(entries) > limit else entries

    except Exception as e:
        print(f"❌ Error reading approved entries: {e}")
        return []


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
