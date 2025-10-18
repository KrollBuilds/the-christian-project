"""Automatically split the full WELS 'What We Believe' text into separate doctrine sections."""

from pathlib import Path
import json
import re

INPUT_PATH = Path("data/raw/wels_manual/doctrine.txt")
OUTPUT_PATH = Path("data/processed/wels_doctrine.jsonl")

def main():
    text = INPUT_PATH.read_text(encoding="utf-8").strip()

    # Split sections on "The Bible and Lutherans teach"
    parts = re.split(r"(?=The Bible and Lutherans teach)", text)

    results = []
    for i, section in enumerate(parts):
        section = section.strip()
        if not section:
            continue

        # Title is the first sentence before the first period
        first_sentence = section.split(".")[0]
        title = first_sentence.replace("The Bible and Lutherans teach that", "").strip().capitalize()
        if not title:
            title = f"Doctrine section {i+1}"

        results.append({
            "id": f"doctrine_{i+1}",
            "type": "doctrine",
            "title": title,
            "content": section
        })

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for record in results:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"✅ Wrote {len(results)} doctrine sections to {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
