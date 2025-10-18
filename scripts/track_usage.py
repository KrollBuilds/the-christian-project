"""Track OpenAI token usage and hosting costs."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

LOG_PATH = Path("data/metrics/usage_log.jsonl")


def record_usage(prompt_tokens: int, completion_tokens: int, model: str) -> None:
    cost = (prompt_tokens + completion_tokens) * 0.000002  # approx cost per token
    entry: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "prompt_tokens": int(prompt_tokens),
        "completion_tokens": int(completion_tokens),
        "model": model,
        "cost_usd": round(cost, 5),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOG_PATH.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(entry) + "\n")
