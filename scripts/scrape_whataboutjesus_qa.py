"""Scrape What About Jesus Q&A articles with incremental update support."""

from __future__ import annotations

import json
import hashlib
import random
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Set, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup, Tag

BASE_URL = "https://whataboutjesus.com"
OUTPUT_DIR = Path("data") / "raw" / "whataboutjesus"
CHECKPOINT_FILE = OUTPUT_DIR / ".checkpoint_qa.json"

# Main Q&A section with pagination
QA_SECTIONS = {
    "questioning-god": "https://whataboutjesus.com/questioning-god/",
}

HEADERS = {
    "User-Agent": "TheChristianProjectBot/1.0 (WELS-approved; educational use)"
}

REQUEST_TIMEOUT = 15
DELAY_RANGE = (1.5, 2.5)  # Respectful rate limiting


@dataclass
class QAArticle:
    """Represents a Q&A article from What About Jesus."""
    id: str  # SHA1 hash of URL for stable ID
    question: str
    answer: str
    url: str
    category: str
    topics: List[str]
    scripture_refs: List[str]
    author: Optional[str]
    date_published: Optional[str]
    scraped_at: str


class Checkpoint:
    """Manages checkpoint state for incremental scraping."""

    def __init__(self, checkpoint_file: Path):
        self.file = checkpoint_file
        self.data = self._load()

    def _load(self) -> Dict:
        """Load checkpoint data from file."""
        if self.file.exists():
            with self.file.open("r", encoding="utf-8") as f:
                return json.load(f)
        return {
            "visited_urls": [],
            "last_run": None,
            "total_articles": 0
        }

    def save(self) -> None:
        """Save checkpoint data to file."""
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

    def update_stats(self, article_count: int) -> None:
        """Update statistics."""
        self.data["last_run"] = datetime.utcnow().isoformat()
        self.data["total_articles"] = article_count


def generate_id(url: str) -> str:
    """Generate stable ID from URL."""
    return hashlib.sha1(url.encode()).hexdigest()[:16]


def load_robot_parser(base_url: str) -> RobotFileParser:
    """Load and parse robots.txt."""
    parser = RobotFileParser()
    parser.set_url(urljoin(base_url, "/robots.txt"))
    try:
        parser.read()
    except Exception as e:
        print(f"Warning: Could not read robots.txt: {e}")
    return parser


def fetch_page(url: str, robot_parser: RobotFileParser) -> Optional[requests.Response]:
    """Fetch a page with robot checking and error handling."""
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


def extract_topics(soup: BeautifulSoup) -> List[str]:
    """Extract topic tags from article."""
    topics = []

    # Look for category/tag elements
    for tag in soup.find_all(["a"], class_=lambda x: x and ("tag" in x.lower() or "category" in x.lower())):
        topic = tag.get_text(strip=True)
        if topic and len(topic) < 50:
            topics.append(topic)

    # Look for meta keywords
    meta_keywords = soup.find("meta", {"name": "keywords"})
    if meta_keywords and meta_keywords.get("content"):
        keywords = [k.strip() for k in meta_keywords["content"].split(",")]
        topics.extend(keywords[:5])  # Limit to first 5

    return list(set(topics))  # Remove duplicates


def extract_scripture_refs(text: str) -> List[str]:
    """Extract Bible references from text (simple pattern matching)."""
    import re

    # Common pattern: Book Chapter:Verse or Book Chapter:Verse-Verse
    pattern = r'\b([1-3]?\s?[A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(\d+):(\d+(?:-\d+)?)\b'
    matches = re.findall(pattern, text)

    refs = []
    for match in matches:
        book, chapter, verse = match
        ref = f"{book.strip()} {chapter}:{verse}"
        refs.append(ref)

    return list(set(refs))[:10]  # Limit to 10 unique refs


def extract_article_metadata(soup: BeautifulSoup) -> Dict[str, Optional[str]]:
    """Extract author and publication date from article."""
    metadata = {
        "author": None,
        "date_published": None
    }

    # Look for author
    author_tag = soup.find(class_=lambda x: x and "author" in x.lower())
    if author_tag:
        metadata["author"] = author_tag.get_text(strip=True)

    # Look for date
    date_tag = soup.find("time")
    if date_tag and date_tag.get("datetime"):
        metadata["date_published"] = date_tag["datetime"]
    else:
        # Alternative: look for date in meta tags
        date_meta = soup.find("meta", {"property": "article:published_time"})
        if date_meta and date_meta.get("content"):
            metadata["date_published"] = date_meta["content"]

    return metadata


def extract_qa_content(soup: BeautifulSoup, url: str) -> Optional[Dict]:
    """Extract Q&A content from article page."""
    # Remove unwanted elements
    for tag in soup.find_all(["header", "nav", "footer", "aside", "script", "style"]):
        tag.decompose()

    # Find main content
    article = soup.find("article") or soup.find("main") or soup.find(class_="content")
    if not article:
        # Fallback to body
        article = soup.find("body")

    if not article:
        return None

    # Extract question (usually the title or h1)
    question = None
    h1 = soup.find("h1")
    if h1:
        question = h1.get_text(strip=True)

    # If no h1, try title tag
    if not question:
        title_tag = soup.find("title")
        if title_tag:
            question = title_tag.get_text(strip=True)
            # Remove site name if present
            question = question.split("|")[0].split("-")[0].strip()

    if not question or len(question) < 10:
        return None

    # Extract answer (main content)
    # Remove h1 from article to avoid duplication
    if h1 and h1.parent == article:
        h1.decompose()

    answer = article.get_text(separator="\n", strip=True)
    answer = "\n".join(line.strip() for line in answer.split("\n") if line.strip())

    if len(answer) < 100:  # Too short to be useful
        return None

    # Extract scripture references from combined text
    full_text = f"{question} {answer}"
    scripture_refs = extract_scripture_refs(full_text)

    # Extract topics
    topics = extract_topics(soup)

    # Extract metadata
    metadata = extract_article_metadata(soup)

    return {
        "question": question,
        "answer": answer,
        "scripture_refs": scripture_refs,
        "topics": topics,
        "author": metadata["author"],
        "date_published": metadata["date_published"]
    }


def find_article_links(soup: BeautifulSoup, base_url: str, section_path: str) -> List[str]:
    """Find all article links on a page."""
    links = []

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue

        # Make absolute URL
        absolute = urljoin(base_url, href)
        parsed = urlparse(absolute)

        # Only keep links within the same domain
        if parsed.netloc != urlparse(base_url).netloc:
            continue

        # Only keep links within the section
        if section_path not in parsed.path:
            continue

        # Clean URL (remove fragment)
        clean_url = parsed._replace(fragment="").geturl()
        links.append(clean_url)

    return list(set(links))


def find_next_page(soup: BeautifulSoup, current_url: str) -> Optional[str]:
    """Find pagination next page link."""
    # Common pagination patterns
    next_link = soup.find("a", class_=lambda x: x and ("next" in x.lower() or "older" in x.lower()))

    if not next_link:
        # Try finding by text
        for link in soup.find_all("a"):
            text = link.get_text(strip=True).lower()
            if text in ["next", "next page", "older posts", "→", "»"]:
                next_link = link
                break

    if next_link and next_link.get("href"):
        return urljoin(current_url, next_link["href"])

    return None


def scrape_qa_section(section_name: str, section_url: str, checkpoint: Checkpoint, robot_parser: RobotFileParser) -> List[QAArticle]:
    """Scrape all articles from a Q&A section with pagination support."""
    articles = []
    current_page_url = section_url
    page_num = 1

    print(f"\n🔍 Scraping section: {section_name}")
    print(f"   Starting URL: {section_url}")

    while current_page_url:
        print(f"\n📄 Page {page_num}: {current_page_url}")

        # Check if already visited (for incremental updates)
        if checkpoint.is_visited(current_page_url):
            print(f"   ⏭️  Already visited, skipping")
            break

        # Fetch the listing page
        response = fetch_page(current_page_url, robot_parser)
        if not response:
            break

        soup = BeautifulSoup(response.text, "html.parser")

        # Find all article links on this page
        article_links = find_article_links(soup, BASE_URL, section_name)
        print(f"   Found {len(article_links)} article links")

        # Scrape each article
        for article_url in article_links:
            # Skip if already scraped
            if checkpoint.is_visited(article_url):
                print(f"   ⏭️  Already scraped: {article_url}")
                continue

            time.sleep(random.uniform(*DELAY_RANGE))

            # Fetch article page
            article_response = fetch_page(article_url, robot_parser)
            if not article_response:
                continue

            # Extract Q&A content
            article_soup = BeautifulSoup(article_response.text, "html.parser")
            content = extract_qa_content(article_soup, article_url)

            if not content:
                print(f"   ⚠️  No content extracted: {article_url}")
                checkpoint.mark_visited(article_url)
                continue

            # Create article object
            article = QAArticle(
                id=generate_id(article_url),
                question=content["question"],
                answer=content["answer"],
                url=article_url,
                category=section_name,
                topics=content["topics"],
                scripture_refs=content["scripture_refs"],
                author=content["author"],
                date_published=content["date_published"],
                scraped_at=datetime.utcnow().isoformat()
            )

            articles.append(article)
            checkpoint.mark_visited(article_url)

            print(f"   ✅ Scraped: {content['question'][:60]}...")

        # Mark listing page as visited
        checkpoint.mark_visited(current_page_url)

        # Find next page
        next_page = find_next_page(soup, current_page_url)
        if next_page and next_page != current_page_url:
            current_page_url = next_page
            page_num += 1
            time.sleep(random.uniform(*DELAY_RANGE))
        else:
            break

    return articles


def save_articles(articles: List[QAArticle], output_file: Path, append: bool = False) -> None:
    """Save articles to JSONL file."""
    output_file.parent.mkdir(parents=True, exist_ok=True)

    mode = "a" if append else "w"
    with output_file.open(mode, encoding="utf-8") as f:
        for article in articles:
            f.write(json.dumps(asdict(article), ensure_ascii=False) + "\n")


def main() -> None:
    """Main scraping function."""
    print("=" * 80)
    print("What About Jesus Q&A Scraper")
    print("=" * 80)

    # Initialize
    checkpoint = Checkpoint(CHECKPOINT_FILE)
    robot_parser = load_robot_parser(BASE_URL)

    all_articles = []

    # Scrape each section
    for section_name, section_url in QA_SECTIONS.items():
        articles = scrape_qa_section(section_name, section_url, checkpoint, robot_parser)
        all_articles.extend(articles)
        print(f"\n✅ Section '{section_name}': {len(articles)} articles")

    if not all_articles:
        print("\n⚠️  No new articles found.")
        return

    # Save results
    output_file = OUTPUT_DIR / "qa_articles.jsonl"

    # Check if we should append (incremental) or overwrite
    append_mode = checkpoint.data["total_articles"] > 0
    save_articles(all_articles, output_file, append=append_mode)

    # Update checkpoint
    total = checkpoint.data["total_articles"] + len(all_articles)
    checkpoint.update_stats(total)
    checkpoint.save()

    # Summary
    print("\n" + "=" * 80)
    print("SCRAPING COMPLETE")
    print("=" * 80)
    print(f"📊 New articles scraped: {len(all_articles)}")
    print(f"📊 Total articles: {total}")
    print(f"📁 Output file: {output_file}")
    print(f"💾 Checkpoint: {CHECKPOINT_FILE}")
    print("=" * 80)


if __name__ == "__main__":
    main()
