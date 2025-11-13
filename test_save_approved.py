#!/usr/bin/env python3
"""Test script to verify save_approved_question() functionality."""

import sys
from pathlib import Path

# Add app directory to path
sys.path.insert(0, str(Path(__file__).parent / "app"))

from utils.training_data import save_approved_question, APPROVED_FILE
from datetime import datetime

def test_save_function():
    """Test the save_approved_question function."""
    print("=" * 60)
    print("Testing save_approved_question() function")
    print("=" * 60)

    # Test data
    test_data = {
        "question": "Test question - What is the meaning of faith?",
        "response": "Test response - Faith is the assurance of things hoped for.",
        "topic": "theology",
        "response_id": f"TEST_{datetime.now().strftime('%Y%m%d%H%M%S')}",
        "editor_notes": "Test entry from verification script"
    }

    print("\n📝 Test Data:")
    for key, value in test_data.items():
        print(f"  {key}: {value[:50]}..." if len(str(value)) > 50 else f"  {key}: {value}")

    print(f"\n📁 Target file: {APPROVED_FILE}")
    print(f"📍 File exists: {APPROVED_FILE.exists()}")

    if APPROVED_FILE.exists():
        size_before = APPROVED_FILE.stat().st_size
        print(f"📊 File size before: {size_before} bytes")
    else:
        size_before = 0
        print("📊 File does not exist yet")

    # Attempt to save
    print("\n🔄 Attempting to save...")
    result = save_approved_question(**test_data)

    # Display results
    print("\n" + "=" * 60)
    print("RESULTS")
    print("=" * 60)

    if result["success"]:
        print("✅ SUCCESS!")
        print(f"   Message: {result['message']}")
        print(f"   File path: {result['file_path']}")
        print(f"   File size: {result.get('file_size', 'N/A')} bytes")
        print(f"   Response ID: {result.get('response_id', 'N/A')}")

        if APPROVED_FILE.exists():
            size_after = APPROVED_FILE.stat().st_size
            size_diff = size_after - size_before
            print(f"\n📈 File size increased by: {size_diff} bytes")

            # Read and display the last line
            with APPROVED_FILE.open("r", encoding="utf-8") as f:
                lines = f.readlines()
                if lines:
                    print(f"\n📄 Last entry in file:")
                    import json
                    last_entry = json.loads(lines[-1])
                    print(f"   Question: {last_entry.get('question', 'N/A')[:60]}...")
                    print(f"   Response ID: {last_entry.get('response_id', 'N/A')}")
                    print(f"   Topic: {last_entry.get('topic', 'N/A')}")
                    print(f"   Status: {last_entry.get('status', 'N/A')}")
                    print(f"   Approved at: {last_entry.get('approved_at', 'N/A')}")
    else:
        print("❌ FAILED!")
        print(f"   Error: {result['message']}")
        print(f"   File path: {result['file_path']}")

    print("\n" + "=" * 60)
    return result["success"]

if __name__ == "__main__":
    try:
        success = test_save_function()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"\n❌ EXCEPTION: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
