"""Process What About Jesus Q&A articles into training format.

Converts scraped Q&A articles from What About Jesus into the standardized
training format used by the project's fine-tuning pipeline.
"""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import List, Dict, Set
from datetime import datetime

# Input/Output paths
INPUT_FILE = Path("data/raw/whataboutjesus/qa_articles.jsonl")
OUTPUT_FILE = Path("data/processed/whataboutjesus_qa.jsonl")

# Existing Q&A for deduplication
EXISTING_QA_FILE = Path("data/processed/qa_clean.jsonl")


def generate_stable_id(question: str, answer: str) -> str:
    """Generate stable hash ID from question and answer."""
    combined = f"{question.lower().strip()}{answer[:200]}"
    return hashlib.sha1(combined.encode()).hexdigest()[:16]


def normalize_text(text: str) -> str:
    """Normalize text for consistency."""
    # Collapse whitespace
    text = " ".join(text.split())
    # Remove common artifacts
    text = text.replace("\u2019", "'").replace("\u2018", "'")
    text = text.replace("\u201c", '"').replace("\u201d", '"')
    return text.strip()


def load_existing_questions() -> Set[str]:
    """Load existing question hashes to avoid duplicates."""
    existing = set()

    if EXISTING_QA_FILE.exists():
        with EXISTING_QA_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    if "question" in data and "answer" in data:
                        qa_id = generate_stable_id(data["question"], data["answer"])
                        existing.add(qa_id)
                except json.JSONDecodeError:
                    continue

    return existing


def load_qa_articles(input_file: Path) -> List[Dict]:
    """Load Q&A articles from input file."""
    articles = []

    if not input_file.exists():
        print(f"⚠️  Input file not found: {input_file}")
        return articles

    with input_file.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                articles.append(data)
            except json.JSONDecodeError as e:
                print(f"⚠️  JSON error on line {line_num}: {e}")

    return articles


def convert_to_training_format(article: Dict) -> Dict:
    """Convert Q&A article to training format."""
    question = normalize_text(article.get("question", ""))
    answer = normalize_text(article.get("answer", ""))

    if not question or not answer:
        raise ValueError("Missing question or answer")

    # Generate stable ID
    qa_id = generate_stable_id(question, answer)

    # Extract metadata
    topics = article.get("topics", [])
    category = article.get("category", "general")
    scripture_refs = article.get("scripture_refs", [])

    # Determine topic (use first topic or category)
    topic = topics[0] if topics else category

    # Build training record
    record = {
        "id": qa_id,
        "question": question,
        "answer": answer,
        "topic": topic,
        "source": "What About Jesus",
        "source_url": article.get("url", ""),
        "scripture_references": scripture_refs,
        "topics": topics,
        "author": article.get("author"),
        "date_published": article.get("date_published"),
        "processed_at": datetime.utcnow().isoformat()
    }

    return record


def filter_quality(record: Dict) -> bool:
    """Filter out low-quality Q&A pairs."""
    question = record["question"]
    answer = record["answer"]

    # Minimum length requirements
    if len(question) < 10:
        return False
    if len(answer) < 100:
        return False

    # Maximum length (avoid overly long content)
    if len(question) > 500:
        return False
    if len(answer) > 10000:
        return False

    return True


def save_processed_qa(records: List[Dict], output_file: Path) -> None:
    """Save processed Q&A records to file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with output_file.open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")


def main() -> None:
    """Main processing function."""
    print("=" * 80)
    print("What About Jesus Q&A Processing")
    print("=" * 80)

    # Load existing Q&A for deduplication
    print("\n📂 Loading existing Q&A data for deduplication...")
    existing_ids = load_existing_questions()
    print(f"   Found {len(existing_ids)} existing Q&A pairs")

    # Load scraped articles
    print(f"\n📂 Loading scraped articles from {INPUT_FILE}...")
    articles = load_qa_articles(INPUT_FILE)
    print(f"   Loaded {len(articles)} articles")

    if not articles:
        print("\n⚠️  No articles to process. Run scrape_whataboutjesus_qa.py first.")
        return

    # Process articles
    print("\n⚙️  Processing articles...")
    processed = []
    duplicates = 0
    errors = 0
    filtered = 0

    for article in articles:
        try:
            # Convert to training format
            record = convert_to_training_format(article)

            # Check for duplicates
            if record["id"] in existing_ids:
                duplicates += 1
                continue

            # Quality filter
            if not filter_quality(record):
                filtered += 1
                continue

            processed.append(record)

        except Exception as e:
            errors += 1
            print(f"   ⚠️  Error processing article: {e}")

    # Save processed records
    if processed:
        print(f"\n💾 Saving {len(processed)} processed Q&A pairs...")
        save_processed_qa(processed, OUTPUT_FILE)

    # Statistics
    print("\n" + "=" * 80)
    print("PROCESSING COMPLETE")
    print("=" * 80)
    print(f"📊 Total articles: {len(articles)}")
    print(f"✅ Successfully processed: {len(processed)}")
    print(f"🔄 Duplicates skipped: {duplicates}")
    print(f"🚫 Filtered (quality): {filtered}")
    print(f"❌ Errors: {errors}")
    print(f"📁 Output file: {OUTPUT_FILE}")

    if processed:
        print("\n📈 Sample questions:")
        for i, record in enumerate(processed[:5], 1):
            q = record["question"]
            q_preview = q[:70] + "..." if len(q) > 70 else q
            print(f"   {i}. {q_preview}")

    print("=" * 80)


if __name__ == "__main__":
    main()
