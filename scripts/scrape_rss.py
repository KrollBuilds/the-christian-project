"""
Automated RSS scraper for trusted Christian theology sources.

Fetches articles from curated RSS feeds, cleans HTML, deduplicates by URL,
and appends new records to data/processed/rss_content.jsonl in the same
format expected by embed_dataset.py.

Run manually:   python scripts/scrape_rss.py
Run via CI:     triggered automatically by GitHub Actions weekly
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set

import feedparser
import requests
from bs4 import BeautifulSoup

# ---------------------------------------------------------------------------
# Output paths
# ---------------------------------------------------------------------------
OUTPUT_PATH = Path("data/processed/rss_content.jsonl")
SEEN_URLS_PATH = Path("data/processed/rss_seen_urls.json")

# ---------------------------------------------------------------------------
# Trusted Christian sources with RSS feeds
# ---------------------------------------------------------------------------
RSS_SOURCES = [
    {
        "url": "https://www.1517.org/feed",
        "source": "1517.org",
        "category": "Lutheran theology",
    },
    {
        "url": "https://www.thegospelcoalition.org/feed/",
        "source": "The Gospel Coalition",
        "category": "Reformed theology",
    },
    {
        "url": "https://www.desiringgod.org/rss/articles",
        "source": "Desiring God",
        "category": "Reformed theology",
    },
    {
        "url": "https://lutheranreformation.org/feed/",
        "source": "Lutheran Reformation",
        "category": "Lutheran theology",
    },
    {
        "url": "https://blog.ligonier.org/feed/",
        "source": "Ligonier Ministries",
        "category": "Reformed theology",
    },
]

MIN_WORD_COUNT = 150  # skip stubs / teasers that have no real content
REQUEST_DELAY = 0.75  # seconds between full-text fetches — be polite


# ---------------------------------------------------------------------------

def _clean_html(raw: str) -> str:
    soup = BeautifulSoup(raw, "html.parser")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    text = soup.get_text(separator=" ")
    return re.sub(r"\s+", " ", text).strip()


def _load_seen_urls() -> Set[str]:
    if SEEN_URLS_PATH.exists():
        return set(json.loads(SEEN_URLS_PATH.read_text(encoding="utf-8")))
    return set()


def _save_seen_urls(urls: Set[str]) -> None:
    SEEN_URLS_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEEN_URLS_PATH.write_text(
        json.dumps(sorted(urls), ensure_ascii=False), encoding="utf-8"
    )


def _fetch_full_text(url: str) -> Optional[str]:
    try:
        resp = requests.get(
            url,
            timeout=12,
            headers={"User-Agent": "TheChristianProject/1.0 (theology RSS aggregator)"},
        )
        if resp.status_code == 200:
            return _clean_html(resp.text)
    except Exception:
        pass
    return None


def _parse_date(entry) -> str:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        try:
            return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()
        except Exception:
            pass
    return ""


# ---------------------------------------------------------------------------

def scrape_all() -> int:
    seen_urls = _load_seen_urls()
    new_records: List[Dict] = []
    new_urls: Set[str] = set()

    for cfg in RSS_SOURCES:
        print(f"\n→ {cfg['source']}")
        try:
            feed = feedparser.parse(cfg["url"])
        except Exception as exc:
            print(f"  ✗ Feed fetch failed: {exc}")
            continue

        for entry in feed.entries:
            url = entry.get("link", "").strip()
            if not url or url in seen_urls or url in new_urls:
                continue

            # Prefer full article content embedded in feed; fall back to summary
            content = ""
            if hasattr(entry, "content") and entry.content:
                content = _clean_html(entry.content[0].get("value", ""))
            if len(content.split()) < MIN_WORD_COUNT and hasattr(entry, "summary"):
                content = _clean_html(entry.summary)

            # If still too short, fetch the full page
            if len(content.split()) < MIN_WORD_COUNT:
                fetched = _fetch_full_text(url)
                if fetched and len(fetched.split()) >= MIN_WORD_COUNT:
                    content = fetched
                time.sleep(REQUEST_DELAY)

            if len(content.split()) < MIN_WORD_COUNT:
                continue

            uid = hashlib.md5(url.encode()).hexdigest()[:12]
            tags = [
                t.term for t in getattr(entry, "tags", []) if hasattr(t, "term")
            ]

            record: Dict = {
                "id": uid,
                "title": entry.get("title", "Untitled").strip(),
                "content": content,
                "source": cfg["source"],
                "category": cfg["category"],
                "type": "web_article",
                "topic": cfg["category"],
                "url": url,
                "event_date": _parse_date(entry),
                "tags": tags,
            }

            new_records.append(record)
            new_urls.add(url)
            print(f"  + {record['title'][:70]}")

    # Append new records to JSONL (never overwrites existing data)
    if new_records:
        OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
        with OUTPUT_PATH.open("a", encoding="utf-8") as fh:
            for rec in new_records:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

    _save_seen_urls(seen_urls | new_urls)
    print(f"\n✅ Scraped {len(new_records)} new articles across {len(RSS_SOURCES)} sources.")
    return len(new_records)


if __name__ == "__main__":
    scrape_all()
