"""Scrape WELS Daily Devotions with incremental update support.

This script scrapes daily devotions from wels.net/serving-you/devotions/
and supports incremental updates to collect new devotions as they're published.

Features:
- Incremental scraping (only new devotions)
- Checkpoint system for resume capability
- Flexible content extraction (handles varying HTML structures)
- Date-based organization
- Rate limiting and respectful crawling
"""

from __future__ import annotations

import json
import hashlib
import random
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://wels.net"
DEVOTIONS_URL = "https://wels.net/serving-you/devotions/"
OUTPUT_DIR = Path("data") / "raw" / "wels_devotions_web"
CHECKPOINT_FILE = OUTPUT_DIR / ".checkpoint_daily.json"

HEADERS = {
    "User-Agent": "TheChristianProjectBot/1.0 (WELS-approved; educational use)"
}

REQUEST_TIMEOUT = 15
DELAY_RANGE = (1.5, 2.5)

# Devotion categories to scrape
CATEGORIES = {
    "daily": "/serving-you/devotions/",
    # Future: can add other categories
    # "family": "/serving-you/devotions/family/",
    # "teen": "/serving-you/devotions/teen/",
}


@dataclass
class Devotion:
    """Represents a devotional entry."""
    id: str  # SHA1 hash of URL
    title: str
    scripture: str
    content: str
    category: str
    url: str
    date_published: Optional[str]
    author: Optional[str]
    image_url: Optional[str]
    scraped_at: str


class DevotionCheckpoint:
    """Manages checkpoint state for devotion scraping."""

    def __init__(self, checkpoint_file: Path):
        self.file = checkpoint_file
        self.data = self._load()

    def _load(self) -> Dict:
        """Load checkpoint data."""
        if self.file.exists():
            with self.file.open("r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "visited_urls": [],
            "last_run": None,
            "total_devotions": 0,
            "latest_date": None
        }

    def save(self) -> None:
        """Save checkpoint data."""
        self.file.parent.mkdir(parents=True, exist_ok=True)
        with self.file.open("w", encoding="utf-8") as f:
            json.dump(self.data, f, indent=2)

    def is_visited(self, url: str) -> bool:
        """Check if URL has been visited."""
        return url in self.data["visited_urls"]

    def mark_visited(self, url: str) -> None:
        """Mark URL as visited."""
        if url not in self.data["visited_urls"]:
            self.data["visited_urls"].append(url)

    def update_stats(self, devotion_count: int, latest_date: Optional[str] = None) -> None:
        """Update statistics."""
        self.data["last_run"] = datetime.utcnow().isoformat()
        self.data["total_devotions"] = devotion_count
        if latest_date:
            self.data["latest_date"] = latest_date


def generate_id(url: str) -> str:
    """Generate stable ID from URL."""
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def load_robot_parser(base_url: str) -> RobotFileParser:
    """Load robots.txt parser."""
    parser = RobotFileParser()
    parser.set_url(urljoin(base_url, "/robots.txt"))
    try:
        parser.read()
    except Exception as e:
        print(f"⚠️  Could not read robots.txt: {e}")
    return parser


def fetch_page(url: str, robot_parser: RobotFileParser) -> Optional[requests.Response]:
    """Fetch page with error handling."""
    if not robot_parser.can_fetch(HEADERS["User-Agent"], url):
        print(f"⚠️  Skipping (robots.txt): {url}")
        return None

    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            print(f"⚠️  HTTP {response.status_code}: {url}")
            return None
        return response
    except requests.RequestException as e:
        print(f"❌ Request error: {url} - {e}")
        return None


def extract_scripture_reference(soup: BeautifulSoup, content_text: str) -> str:
    """Extract scripture reference from devotion."""
    # Try to find scripture in common locations
    scripture = "Unknown"

    # Pattern 1: Look for scripture reference in specific elements
    scripture_elem = soup.find(class_=lambda x: x and "scripture" in x.lower())
    if scripture_elem:
        scripture = scripture_elem.get_text(strip=True)
        return scripture

    # Pattern 2: Look for common scripture patterns in text
    # e.g., "John 3:16", "Psalm 23:1-6", "1 Corinthians 13"
    pattern = r'\b([1-3]?\s?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(\d+)(?::(\d+(?:-\d+)?))?\b'
    match = re.search(pattern, content_text[:500])  # Check first 500 chars
    if match:
        scripture = match.group(0)

    return scripture


def extract_date(soup: BeautifulSoup) -> Optional[str]:
    """Extract publication date from article."""
    # Try time element first
    time_elem = soup.find("time")
    if time_elem and time_elem.get("datetime"):
        return time_elem["datetime"]

    # Try meta tags
    date_meta = soup.find("meta", {"property": "article:published_time"})
    if date_meta and date_meta.get("content"):
        return date_meta["content"]

    # Try date in URL (common pattern: /2024/01/15/...)
    # This will be handled in the calling function

    return None


def extract_author(soup: BeautifulSoup) -> Optional[str]:
    """Extract author from article."""
    # Try author element
    author_elem = soup.find(class_=lambda x: x and "author" in x.lower())
    if author_elem:
        return author_elem.get_text(strip=True)

    # Try meta tag
    author_meta = soup.find("meta", {"name": "author"})
    if author_meta and author_meta.get("content"):
        return author_meta["content"]

    return None


def extract_devotion_content(soup: BeautifulSoup, url: str, category: str) -> Optional[Dict]:
    """Extract devotion content from page with flexible structure handling."""
    # Remove unwanted elements
    for tag in soup.find_all(["header", "nav", "footer", "aside", "script", "style", "form"]):
        tag.decompose()

    # Find main content container - try multiple approaches
    content_container = None

    # Approach 1: Look for article tag
    content_container = soup.find("article")

    # Approach 2: Look for main tag
    if not content_container:
        content_container = soup.find("main")

    # Approach 3: Look for common content classes
    if not content_container:
        content_container = soup.find(class_=lambda x: x and any(
            term in x.lower() for term in ["content", "post", "entry", "devotion"]
        ))

    # Approach 4: Fallback to body
    if not content_container:
        content_container = soup.find("body")

    if not content_container:
        return None

    # Extract title
    title = None
    h1 = soup.find("h1")
    if h1:
        title = h1.get_text(strip=True)

    if not title:
        title_tag = soup.find("title")
        if title_tag:
            title = title_tag.get_text(strip=True).split("|")[0].split("-")[0].strip()

    if not title or len(title) < 3:
        title = "Daily Devotion"

    # Extract content text
    content_text = content_container.get_text(separator="\n", strip=True)
    content_text = "\n".join(line.strip() for line in content_text.split("\n") if line.strip())

    if len(content_text) < 100:
        return None

    # Extract scripture reference
    scripture = extract_scripture_reference(soup, content_text)

    # Extract date
    date_published = extract_date(soup)

    # Try to extract date from URL if not found
    if not date_published:
        date_match = re.search(r'/(\d{4})/(\d{2})/(\d{2})/', url)
        if date_match:
            year, month, day = date_match.groups()
            date_published = f"{year}-{month}-{day}"

    # Extract author
    author = extract_author(soup)

    # Extract featured image
    image_url = None
    img = soup.find("img", class_=lambda x: x and "featured" in x.lower())
    if not img:
        img = soup.find("img")
    if img and img.get("src"):
        image_url = urljoin(BASE_URL, img["src"])

    return {
        "title": title,
        "scripture": scripture,
        "content": content_text,
        "date_published": date_published,
        "author": author,
        "image_url": image_url
    }


def find_devotion_links(soup: BeautifulSoup, base_url: str) -> List[str]:
    """Find devotion article links on a page."""
    links = []

    # Look for links within devotion listing containers
    containers = soup.find_all(class_=lambda x: x and any(
        term in x.lower() for term in ["post", "devotion", "article", "entry"]
    ))

    if not containers:
        # Fallback to all links
        containers = [soup]

    for container in containers:
        for anchor in container.find_all("a", href=True):
            href = anchor["href"]

            # Skip non-article links
            if any(skip in href for skip in ["#", "mailto:", "tel:", ".pdf", ".jpg", ".png"]):
                continue

            # Make absolute
            absolute = urljoin(base_url, href)
            parsed = urlparse(absolute)

            # Only same domain
            if parsed.netloc != urlparse(base_url).netloc:
                continue

            # Only devotion paths
            if "/devotions/" not in parsed.path and "/devotion/" not in parsed.path:
                continue

            clean_url = parsed._replace(fragment="").geturl()
            links.append(clean_url)

    return list(set(links))


def find_load_more_button(soup: BeautifulSoup) -> Optional[str]:
    """Find 'Load More' button or next page link."""
    # Look for load more buttons
    load_more = soup.find("button", class_=lambda x: x and "load" in x.lower())
    if load_more:
        # If it's an AJAX button, we might need a different approach
        # For now, return None as this requires JavaScript execution
        return None

    # Look for pagination next link
    next_link = soup.find("a", class_=lambda x: x and any(
        term in x.lower() for term in ["next", "older", "previous"]
    ))

    if next_link and next_link.get("href"):
        return urljoin(BASE_URL, next_link["href"])

    return None


def scrape_devotions(category: str, category_url: str, checkpoint: DevotionCheckpoint,
                    robot_parser: RobotFileParser, max_pages: int = 50) -> List[Devotion]:
    """Scrape devotions from a category with pagination."""
    devotions = []
    current_url = category_url
    page_num = 1

    print(f"\n🔍 Scraping category: {category}")
    print(f"   Starting URL: {category_url}")

    visited_listing_pages = set()

    while current_url and page_num <= max_pages:
        # Avoid infinite loops
        if current_url in visited_listing_pages:
            break
        visited_listing_pages.add(current_url)

        print(f"\n📄 Page {page_num}: {current_url}")

        # Fetch listing page
        response = fetch_page(current_url, robot_parser)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")

        # Find devotion links
        devotion_links = find_devotion_links(soup, BASE_URL)
        print(f"   Found {len(devotion_links)} devotion links")

        new_devotions = 0

        # Scrape each devotion
        for devotion_url in devotion_links:
            # Skip if already scraped
            if checkpoint.is_visited(devotion_url):
                continue

            time.sleep(random.uniform(*DELAY_RANGE))

            # Fetch devotion page
            devotion_response = fetch_page(devotion_url, robot_parser)
            if not devotion_response:
                checkpoint.mark_visited(devotion_url)
                continue

            # Extract content
            devotion_soup = BeautifulSoup(devotion_response.text, "html.parser")
            content = extract_devotion_content(devotion_soup, devotion_url, category)

            if not content:
                print(f"   ⚠️  No content: {devotion_url}")
                checkpoint.mark_visited(devotion_url)
                continue

            # Create devotion object
            devotion = Devotion(
                id=generate_id(devotion_url),
                title=content["title"],
                scripture=content["scripture"],
                content=content["content"],
                category=category,
                url=devotion_url,
                date_published=content["date_published"],
                author=content["author"],
                image_url=content["image_url"],
                scraped_at=datetime.utcnow().isoformat()
            )

            devotions.append(devotion)
            checkpoint.mark_visited(devotion_url)
            new_devotions += 1

            print(f"   ✅ Scraped: {content['title'][:60]}...")

        print(f"   📊 New devotions from this page: {new_devotions}")

        # If no new devotions found, we might have reached content we already have
        if new_devotions == 0 and len(devotion_links) > 0:
            print("   ⏭️  No new devotions found, stopping pagination")
            break

        # Find next page
        next_url = find_load_more_button(soup)
        if next_url and next_url != current_url:
            current_url = next_url
            page_num += 1
            time.sleep(random.uniform(*DELAY_RANGE))
        else:
            print("   ℹ️  No more pages found")
            break

    return devotions


def save_devotions(devotions: List[Devotion], output_file: Path, append: bool = False) -> None:
    """Save devotions to JSONL file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    mode = "a" if append else "w"
    with output_file.open(mode, encoding="utf-8") as f:
        for devotion in devotions:
            f.write(json.dumps(asdict(devotion), ensure_ascii=False) + "\n")


def main() -> None:
    """Main scraping function."""
    print("=" * 80)
    print("WELS Daily Devotions Scraper")
    print("=" * 80)
    print(f"Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    # Initialize
    checkpoint = DevotionCheckpoint(CHECKPOINT_FILE)
    robot_parser = load_robot_parser(BASE_URL)

    if checkpoint.data["last_run"]:
        print(f"Last run: {checkpoint.data['last_run']}")
        print(f"Total devotions collected: {checkpoint.data['total_devotions']}")

    all_devotions = []

    # Scrape each category
    for category, category_url in CATEGORIES.items():
        devotions = scrape_devotions(category, category_url, checkpoint, robot_parser)
        all_devotions.extend(devotions)
        print(f"\n✅ Category '{category}': {len(devotions)} new devotions")

    if not all_devotions:
        print("\n⚠️  No new devotions found.")
        checkpoint.save()
        return

    # Find latest date
    latest_date = None
    for d in all_devotions:
        if d.date_published and (not latest_date or d.date_published > latest_date):
            latest_date = d.date_published

    # Save results
    output_file = OUTPUT_DIR / "daily_devotions.jsonl"
    append_mode = checkpoint.data["total_devotions"] > 0
    save_devotions(all_devotions, output_file, append=append_mode)

    # Update checkpoint
    total = checkpoint.data["total_devotions"] + len(all_devotions)
    checkpoint.update_stats(total, latest_date)
    checkpoint.save()

    # Summary
    print("\n" + "=" * 80)
    print("SCRAPING COMPLETE")
    print("=" * 80)
    print(f"📊 New devotions scraped: {len(all_devotions)}")
    print(f"📊 Total devotions: {total}")
    print(f"📅 Latest date: {latest_date or 'Unknown'}")
    print(f"📁 Output file: {output_file}")
    print(f"💾 Checkpoint: {CHECKPOINT_FILE}")
    print("=" * 80)


if __name__ == "__main__":
    main()
