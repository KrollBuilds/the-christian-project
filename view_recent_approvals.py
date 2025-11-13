#!/usr/bin/env python3
"""View recent approved training entries."""

import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "app"))

from utils.training_data import get_recent_approved_entries, APPROVED_FILE
from datetime import datetime

def main():
    """Display recent approved entries."""
    print("=" * 80)
    print("RECENT APPROVED TRAINING ENTRIES")
    print("=" * 80)
    print(f"📁 File: {APPROVED_FILE}")
    print(f"📍 Exists: {APPROVED_FILE.exists()}")

    if APPROVED_FILE.exists():
        file_size = APPROVED_FILE.stat().st_size
        print(f"📊 Size: {file_size} bytes")

    print("\n" + "=" * 80)

    entries = get_recent_approved_entries(limit=10)

    if not entries:
        print("❌ No approved entries found.")
        return

    print(f"📋 Showing {len(entries)} most recent entries:\n")

    for i, entry in enumerate(reversed(entries), 1):
        print(f"\n{'─' * 80}")
        print(f"Entry #{i}")
        print(f"{'─' * 80}")
        print(f"Response ID:  {entry.get('response_id', 'N/A')}")
        print(f"Topic:        {entry.get('topic', 'N/A')}")
        print(f"Approved At:  {entry.get('approved_at', 'N/A')}")
        print(f"Status:       {entry.get('status', 'N/A')}")

        question = entry.get('question', 'N/A')
        if len(question) > 100:
            question = question[:100] + "..."
        print(f"Question:     {question}")

        response = entry.get('response', 'N/A')
        if len(response) > 150:
            response = response[:150] + "..."
        print(f"Response:     {response}")

        editor_notes = entry.get('editor_notes', '')
        if editor_notes:
            print(f"Notes:        {editor_notes}")

    print("\n" + "=" * 80)
    print(f"✅ Total entries in file: {len(entries)}")
    print("=" * 80)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
