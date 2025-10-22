"""
Converts and merges WELS 'What We Believe' and 'Doctrine' texts into a single JSONL dataset.

Features:
- Handles both numbered and narrative doctrinal formats.
- Cleans and normalizes text (punctuation, whitespace, Unicode).
- Extracts each numbered statement as its own entry.
- Pulls and stores Scripture references for future retrieval.
- Merges multiple source files (whatwebelive.txt + doctrine.txt).
- Creates stable hashed IDs for deduplication and FAISS embedding.
"""

from pathlib import Path
import json
import re
import hashlib
import unicodedata

# --- Input sources ---
INPUT_PATHS = [
    Path("data/raw/wels_manual/whatwebelive.txt"),
    Path("data/raw/wels_manual/doctrine.txt"),
]
OUTPUT_PATH = Path("data/processed/wels_doctrine.jsonl")

SCRIPTURE_PATTERN = re.compile(
    r"\b([1-3]?\s?[A-Z][a-z]+)\s\d{1,3}:\d{1,3}(?:[-–]\d{1,3})?\b"
)

def normalize_unicode(text: str) -> str:
    """Normalize Unicode punctuation and spaces."""
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("’", "'").replace("“", '"').replace("”", '"')
    text = text.replace("–", "-").replace("—", "-")
    return text.strip()

def clean_text(text: str) -> str:
    """Normalize whitespace and punctuation spacing."""
    text = normalize_unicode(text)
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"\s+\.", ".", text)
    text = re.sub(r"\s+,", ",", text)
    return text.strip()

def extract_title_and_points(text: str):
    """Extract a doctrine title and its numbered sub-points."""
    title_match = re.match(r"^(.*?)\s*(?=\d\.\s+)", text, flags=re.DOTALL)
    title = title_match.group(1).strip() if title_match else "Untitled Section"

    # Split numbered points
    points = re.split(r"\s*(?=\d\.\s+)", text)
    cleaned_points = []
    for p in points:
        if not re.match(r"\d\.\s+", p):
            continue
        point_num = re.match(r"(\d+)\.\s+", p).group(1)
        content = clean_text(re.sub(r"^\d+\.\s+", "", p))
        if not content:
            continue
        refs = SCRIPTURE_PATTERN.findall(content)
        cleaned_points.append({
            "point": point_num,
            "content": content,
            "scripture_refs": refs
        })
    return title, cleaned_points

def make_hash_id(text: str) -> str:
    """Generate a short stable hash ID for deduplication and re-indexing."""
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return h[:12]

def process_file(path: Path):
    """Process one input file and return list of cleaned doctrinal records."""
    if not path.exists():
        print(f"⚠️ Skipping missing file: {path}")
        return []

    raw_text = path.read_text(encoding="utf-8").strip()
    raw_text = re.sub(r"\r\n", "\n", raw_text)

    # Split into major doctrinal sections by double newline and capital letter
    doctrine_sections = re.split(r"\n{2,}(?=[A-Z])", raw_text)

    file_records = []
    for i, section in enumerate(doctrine_sections, start=1):
        section = section.strip()
        if not section:
            continue

        if "The Bible and Lutherans teach" in section:
            title = section.split(".")[0].replace(
                "The Bible and Lutherans teach that", ""
            ).strip().capitalize()
            points = [{"point": "1", "content": clean_text(section), "scripture_refs": []}]
        else:
            title, points = extract_title_and_points(section)

        for p in points:
            unique_id = make_hash_id(title + p["content"])
            record = {
                "id": f"{path.stem}_sec_{i}_pt_{p['point']}_{unique_id}",
                "source_file": path.name,
                "type": "doctrine",
                "title": title,
                "point_number": p["point"],
                "content": p["content"],
                "scripture_refs": p.get("scripture_refs", []),
                "length_tokens_est": len(p["content"].split()),
            }
            file_records.append(record)

    print(f"✅ Processed {len(file_records)} sections from {path.name}")
    return file_records

def main():
    all_records = []
    for path in INPUT_PATHS:
        all_records.extend(process_file(path))

    if not all_records:
        print("⚠️ No records processed. Check your input paths.")
        return

    # Sort for consistent output
    all_records.sort(key=lambda r: (r["source_file"], r["title"], int(r["point_number"])))

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        for rec in all_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    print(f"📘 Total doctrinal entries written: {len(all_records)} → {OUTPUT_PATH}")

if __name__ == "__main__":
    main()
