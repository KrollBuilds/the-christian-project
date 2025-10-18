import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Iterable, List, Optional


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a fine-tuning dataset from reviewed responses."
    )
    parser.add_argument(
        "--min_tone",
        type=float,
        default=0.7,
        help="Minimum tone_score required for inclusion (default: 0.7).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=None,
        help="Only include reviews newer than N days.",
    )
    parser.add_argument(
        "--input_path",
        type=Path,
        default=Path("data/feedback/review_log.jsonl"),
        help="Path to the reviewed responses JSONL file.",
    )
    parser.add_argument(
        "--output_path",
        type=Path,
        default=Path("data/processed/training/approved_dataset.jsonl"),
        help="Where to write the approved dataset.",
    )
    return parser.parse_args()


def load_reviews(path: Path) -> Iterable[dict]:
    if not path.exists():
        raise FileNotFoundError(f"Input file not found: {path}")

    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid JSON on line {line_number}: {exc}") from exc


def parse_timestamp(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def normalize_answer(answer: str) -> str:
    # Collapse multi-line answers into a single line with clean spacing.
    normalized = " ".join(segment.strip() for segment in answer.splitlines())
    return normalized.strip()


def filter_reviews(
    reviews: Iterable[dict], min_tone: float, min_timestamp: Optional[datetime]
) -> List[dict]:
    approved: List[dict] = []
    for review in reviews:
        if review.get("accuracy") != "Sound":
            continue
        if review.get("tone") != "Pastoral":
            continue
        if not review.get("question") or not review.get("answer"):
            continue

        tone_score = review.get("tone_score")
        if tone_score is None or not isinstance(tone_score, (float, int)):
            continue
        if tone_score < min_tone:
            continue

        if min_timestamp is not None:
            timestamp = parse_timestamp(review.get("timestamp", ""))
            if timestamp is None or timestamp < min_timestamp:
                continue

        approved.append(review)
    return approved


def build_examples(reviews: Iterable[dict]) -> List[dict]:
    examples: List[dict] = []
    for review in reviews:
        question = review["question"].strip()
        answer = normalize_answer(review["answer"])
        if not answer:
            continue
        examples.append(
            {
                "prompt": f"User: {question}\nAnswer:",
                "completion": f" {answer}",
            }
        )
    return examples


def write_examples(path: Path, examples: List[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as destination:
        for example in examples:
            destination.write(json.dumps(example, ensure_ascii=True) + "\n")


def validate_output(path: Path, sample_size: int = 3) -> None:
    try:
        with path.open("r", encoding="utf-8") as handle:
            for _ in range(sample_size):
                line = handle.readline()
                if not line:
                    break
                json.loads(line)
    except json.JSONDecodeError as exc:
        print(f"❌ JSON validation failed: {exc}", file=sys.stderr)
        sys.exit(1)


def main() -> None:
    args = parse_args()

    min_timestamp: Optional[datetime] = None
    if args.days is not None:
        min_timestamp = datetime.utcnow() - timedelta(days=args.days)

    try:
        reviews = list(load_reviews(args.input_path))
    except (FileNotFoundError, ValueError) as exc:
        print(f"❌ Failed to load reviews: {exc}", file=sys.stderr)
        sys.exit(1)

    filtered = filter_reviews(reviews, args.min_tone, min_timestamp)
    examples = build_examples(filtered)
    write_examples(args.output_path, examples)
    validate_output(args.output_path)

    print(
        f"✅ Wrote {len(examples)} approved examples to {args.output_path}",
        flush=True,
    )

    # Future expansion: this dataset will feed local LoRA/PEFT fine-tuning, OpenAI fine-tuning,
    # or refreshed sentence-transformer embeddings.


if __name__ == "__main__":
    main()
