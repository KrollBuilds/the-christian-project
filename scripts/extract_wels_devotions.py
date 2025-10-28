import os
import re
import json
from pathlib import Path
from pdfminer.high_level import extract_text

# ----------------------------
# CONFIGURATION
# ----------------------------
INPUT_DIR = Path("data/wels_devotions/family")  # folder containing PDFs
OUTPUT_FILE = Path("data/cleaned/devotions_family_cleaned.jsonl")

# ----------------------------
# TEXT CLEANUP HELPERS
# ----------------------------
def clean_text(text: str) -> str:
    """Basic normalization and cleanup for devotion text."""
    # Remove excessive whitespace and newlines
    text = re.sub(r'\s+', ' ', text)
    # Remove stray headers or form-feed remnants
    text = text.replace("In the name of the Father and of the Son and of the Holy Spirit. Amen.", "").strip()
    return text

def parse_devotion(text: str, filename: str):
    """Extract structured components from devotion text."""
    # Extract title
    title_match = re.search(r'\n?([A-Z][A-Za-z\s\’\'-]+)\s*\n\s*[A-Z][a-z]+\s*\d*[:\.0-9\-–]*', text)
    title = title_match.group(1).strip() if title_match else filename.replace(".pdf", "")

    # Extract scripture passage
    scripture_match = re.search(r'Read[:\s]+([A-Za-z0-9:\-–\s]+)', text)
    scripture = scripture_match.group(1).strip() if scripture_match else "Unknown Passage"

    # Extract closing prayer section
    closing_match = re.search(r'(Closing Prayer[:]?.*?Amen\.)', text, re.IGNORECASE | re.DOTALL)
    closing_prayer = closing_match.group(1).strip() if closing_match else ""

    # Extract discussion questions section
    questions_match = re.search(r'The questions below.*?(Closing Prayer|$)', text, re.IGNORECASE | re.DOTALL)
    questions = questions_match.group(0).strip() if questions_match else ""

    # Extract main devotion body (before questions)
    body_split = text.split("The questions below")[0].strip() if "The questions below" in text else text
    body_text = clean_text(body_split)

    # Create the record
    record = {
        "title": title,
        "scripture": scripture,
        "category": "Family Devotion",
        "source": "WELS Family Devotions",
        "filename": filename,
        "body": body_text,
        "questions": questions,
        "closing_prayer": closing_prayer,
        "text_for_embedding": f"{title}. {scripture}. {body_text} {closing_prayer}"
    }
    return record

# ----------------------------
# MAIN EXTRACTION PIPELINE
# ----------------------------
def main():
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    records = []

    for pdf in sorted(INPUT_DIR.glob("*.pdf")):
        try:
            raw_text = extract_text(pdf)
            cleaned = clean_text(raw_text)
            record = parse_devotion(cleaned, pdf.name)
            records.append(record)
            print(f"✓ Parsed {pdf.name}")
        except Exception as e:
            print(f"⚠️ Error processing {pdf.name}: {e}")

    # Write JSONL
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        for r in records:
            json.dump(r, f, ensure_ascii=False)
            f.write("\n")

    print(f"\n✅ Extracted {len(records)} devotions → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
