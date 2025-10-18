"""Utility to clean the raw Q&A export into a JSONL dataset."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Iterable, Optional

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[1]
RAW_CSV_PATH = PROJECT_ROOT / "data" / "raw" / "QA-Export.csv"
OUTPUT_JSONL_PATH = PROJECT_ROOT / "data" / "processed" / "qa_clean.jsonl"

# Aliases accommodate the most common header variations we might receive.
FIELD_ALIASES: Dict[str, Iterable[str]] = {
    "id": ("id", "qa_id", "identifier", "question_id", "Question ID"),
    "question": ("question", "prompt", "q"),
    "answer": ("answer", "response", "a"),
    "created": ("created", "created_at", "date_created", "timestamp"),
    "modified": ("modified", "updated", "last_modified", "updated_at"),
}


def locate_column(
    normalized_columns: Dict[str, str], aliases: Iterable[str]
) -> Optional[str]:
    """Return the actual column name if any alias matches the normalized map."""
    for alias in aliases:
        key = alias.lower().replace(" ", "_")
        if key in normalized_columns:
            return normalized_columns[key]
    return None


def main() -> None:
    if not RAW_CSV_PATH.exists():
        raise FileNotFoundError(f"Expected CSV at {RAW_CSV_PATH}")

    df = pd.read_csv(
        RAW_CSV_PATH,
        quotechar='"',
        doublequote=True,
        escapechar="\\",
        engine="python",
        on_bad_lines="skip",
    )

    normalized_columns = {
        column.lower().replace(" ", "_"): column for column in df.columns
    }

    selected_columns: Dict[str, str] = {}
    for field, aliases in FIELD_ALIASES.items():
        column_name = locate_column(normalized_columns, aliases)
        if column_name is None:
            if field in {"created", "modified"}:
                selected_columns[field] = None
                continue
            raise KeyError(
                f"Unable to locate a column for '{field}'. "
                f"Available headers: {list(df.columns)}"
            )
        selected_columns[field] = column_name

    # Build the clean dataset row by row so we can gracefully handle missing fields.
    OUTPUT_JSONL_PATH.parent.mkdir(parents=True, exist_ok=True)
    written_rows = 0
    with OUTPUT_JSONL_PATH.open("w", encoding="utf-8") as jsonl_file:
        for _, row in df.iterrows():
            record = {
                "id": row[selected_columns["id"]],
                "question": row[selected_columns["question"]],
                "answer": row[selected_columns["answer"]],
                "created": (
                    row[selected_columns["created"]]
                    if selected_columns["created"] is not None
                    else None
                ),
                "modified": (
                    row[selected_columns["modified"]]
                    if selected_columns["modified"] is not None
                    else None
                ),
            }
            jsonl_file.write(json.dumps(record, ensure_ascii=True) + "\n")
            written_rows += 1

    print(f"Wrote {written_rows} rows to {OUTPUT_JSONL_PATH}")


if __name__ == "__main__":
    main()
