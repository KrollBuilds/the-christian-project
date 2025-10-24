"""Simple FastAPI endpoints that allow the Review Dashboard to ingest chat responses."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, HTTPException, Request, status

LOG_PATH = Path(os.getenv("REVIEW_QUEUE_PATH", "data/review_queue.jsonl"))
LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

API_KEY = os.getenv("REVIEW_API_KEY")

app = FastAPI(title="The Christian Review API")


async def _require_api_key(request: Request) -> None:
    """Enforce bearer token authentication when REVIEW_API_KEY is configured."""
    if not API_KEY:
        return
    auth_header = request.headers.get("Authorization")
    if not auth_header or not auth_header.startswith("Bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication token.",
        )
    token = auth_header.split(" ", 1)[1]
    if token != API_KEY:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token.",
        )


def _persist_review(payload: Dict[str, Any]) -> None:
    """Append a single review payload to the JSONL queue."""
    with LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False) + "\n")


def _load_reviews() -> List[Dict[str, Any]]:
    """Load queued reviews from disk."""
    if not LOG_PATH.exists():
        return []
    with LOG_PATH.open("r", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


@app.post("/api/submit_review")
async def submit_review(request: Request) -> Dict[str, str]:
    await _require_api_key(request)
    payload = await request.json()
    payload["timestamp"] = datetime.now(timezone.utc).isoformat()
    _persist_review(payload)
    return {"status": "queued"}


@app.get("/api/get_pending_reviews")
async def get_pending_reviews() -> List[Dict[str, Any]]:
    return _load_reviews()
