"""
Normalize pastoral teaching transcripts into JSONL records for embedding.

Expected input:
    data/raw/pastoral_teachings/manifest.json  → list of entries with metadata.

Each manifest entry should include:
    {
        "id": "unique-sermon-or-lesson-id",
        "title": "Hope in Christ",
        "topic": "Comfort",
        "pastor": "Rev. Jane Doe",
        "delivered_on": "2024-09-15",
        "series": "Advent Evening Devotions",
        "tags": ["advent", "comfort"],
        "source_path": "sermons/hope_in_christ.txt"
    }

The referenced source_path is resolved relative to the manifest file.
Plain-text and Markdown files are supported. All HTML/Markdown is stripped to text.

Output:
    data/processed/pastoral_teachings.jsonl  → 1 JSON object per teaching.

Use this before running scripts/embed_dataset.py to refresh retrieval embeddings.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List

MANIFEST_PATH = Path("data/raw/pastoral_teachings/manifest.json")
OUTPUT_PATH = Path("data/processed/pastoral_teachings.jsonl")
VALID_EXTENSIONS = {".txt", ".md", ".markdown"}


def load_manifest(path: Path) -> List[Dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(
            f"Manifest not found at {path}. Add transcripts and metadata before running this script."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        entries = data.get("entries", [])
    elif isinstance(data, list):
        entries = data
    else:
        raise ValueError("Manifest must be a list or contain an 'entries' list.")
    if not entries:
        raise ValueError("Manifest is empty; nothing to process.")
    return entries


def clean_text(raw: str) -> str:
    """Normalize whitespace and strip simple Markdown/HTML artifacts."""
    # Remove Markdown headings and emphasis markers while preserving wording.
    text = re.sub(r"^#+\s*", "", raw, flags=re.MULTILINE)
    text = re.sub(r"[*_]{1,3}([^*_]+)[*_]{1,3}", r"\1", text)
    # Drop inline HTML tags.
    text = re.sub(r"<[^>]+>", " ", text)
    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def read_source_text(base_dir: Path, relative_path: str) -> str:
    source_path = (base_dir / relative_path).resolve()
    if source_path.suffix.lower() not in VALID_EXTENSIONS:
        raise ValueError(f"Unsupported transcript format: {source_path.name}")
    if not source_path.exists():
        raise FileNotFoundError(f"Transcript file not found: {source_path}")
    return clean_text(source_path.read_text(encoding="utf-8"))


def normalise_entry(entry: Dict[str, str], base_dir: Path) -> Dict[str, object]:
    required = ["id", "title", "pastor", "source_path"]
    missing = [key for key in required if not entry.get(key)]
    if missing:
        raise ValueError(f"Manifest entry missing required fields: {missing}")

    content = read_source_text(base_dir, entry["source_path"])
    if not content:
        raise ValueError(f"Transcript for {entry['id']} is empty.")

    record: Dict[str, object] = {
        "id": entry["id"],
        "type": "pastoral_teaching",
        "title": entry["title"],
        "pastor": entry.get("pastor"),
        "event_date": entry.get("delivered_on"),
        "topic": entry.get("topic"),
        "source": entry.get("series") or entry.get("source_title"),
        "tags": entry.get("tags", []),
        "content": content,
        "length_tokens_est": len(content.split()),
        "source_path": entry["source_path"],
    }
    return record


def main() -> None:
    entries = load_manifest(MANIFEST_PATH)
    base_dir = MANIFEST_PATH.parent

    normalised_records: List[Dict[str, object]] = []
    for entry in entries:
        try:
            record = normalise_entry(entry, base_dir)
        except Exception as exc:
            raise RuntimeError(f"Failed to normalise entry {entry!r}: {exc}") from exc
        normalised_records.append(record)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as fh:
        for record in normalised_records:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")

    print(f"✅ Normalised {len(normalised_records)} pastoral teachings → {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
