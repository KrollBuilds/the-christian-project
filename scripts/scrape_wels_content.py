"""Scrape selected public WELS resources into a structured JSONL dataset."""

from __future__ import annotations

import json
import random
import time
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Set
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://wels.net"
OUTPUT_PATH = Path("data") / "raw" / "wels_articles" / "wels_content.jsonl"

SECTIONS: Dict[str, str] = {
    "/serving-you/what-we-believe/": "doctrine",
    "/devotions/": "devotion",
    "/news-media/": "news",
    "/serving-you/wels-topical-qa/": "qa",
}

HEADERS = {
    "User-Agent": (
        "TheChristianProjectBot/0.1 (+https://github.com/)"
    )
}

REQUEST_TIMEOUT = 15
DELAY_RANGE = (1.0, 2.0)


@dataclass
class PageResult:
    title: str
    url: str
    section_type: str
    content: str


def load_robot_parser() -> RobotFileParser:
    """Load robots.txt parser using requests to avoid 403 errors."""
    parser = RobotFileParser()
    robots_url = urljoin(BASE_URL, "/robots.txt")

    try:
        # Use requests with proper headers to fetch robots.txt
        response = requests.get(robots_url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code == 200:
            # Parse the content manually
            parser.parse(response.text.splitlines())
            print(f"✓ Loaded robots.txt from {robots_url}")
        else:
            print(f"⚠️  Could not fetch robots.txt (HTTP {response.status_code}), assuming allowed")
            # Default to allowing all for WELS-affiliated educational sites
            parser.parse(["User-agent: *", "Allow: /"])
    except Exception as e:
        print(f"⚠️  Could not read robots.txt: {e}, assuming allowed")
        # Default to allowing all if robots.txt is unavailable
        parser.parse(["User-agent: *", "Allow: /"])

    return parser


def clean_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["header", "nav", "footer", "aside", "script", "style"]):
        tag.decompose()
    main = soup.find("main")
    if main:
        soup = main
    return " ".join(soup.get_text(separator=" ", strip=True).split())


def extract_links(soup: BeautifulSoup, base_path: str) -> Iterable[str]:
    for anchor in soup.find_all("a", href=True):
        href = anchor["href"]
        if href.startswith("#") or href.startswith("mailto:") or href.startswith("tel:"):
            continue
        absolute = urljoin(BASE_URL, href)
        parsed = urlparse(absolute)
        if parsed.netloc != urlparse(BASE_URL).netloc:
            continue
        if not parsed.path.startswith(base_path):
            continue
        yield parsed._replace(fragment="").geturl()


def fetch(url: str, robot_parser: RobotFileParser) -> requests.Response | None:
    if not robot_parser.can_fetch(HEADERS["User-Agent"], url):
        print(f"Skipping disallowed by robots: {url}")
        return None
    try:
        response = requests.get(url, headers=HEADERS, timeout=REQUEST_TIMEOUT)
        if response.status_code != 200:
            print(f"Non-200 status {response.status_code} for {url}")
            return None
        return response
    except requests.RequestException as exc:
        print(f"Request error for {url}: {exc}")
        return None


def crawl_section(start_path: str, section_type: str, robot_parser: RobotFileParser) -> List[PageResult]:
    start_url = urljoin(BASE_URL, start_path)
    queue = [start_url]
    visited: Set[str] = set()
    results: List[PageResult] = []

    while queue:
        current = queue.pop(0)
        if current in visited:
            continue
        visited.add(current)

        if not robot_parser.can_fetch(HEADERS["User-Agent"], current):
            print(f"Skipping disallowed by robots: {current}")
            continue

        response = fetch(current, robot_parser)
        if response is None:
            continue

        soup = BeautifulSoup(response.text, "html.parser")
        title_tag = soup.find("h1")
        title = title_tag.get_text(strip=True) if title_tag else soup.title.string if soup.title else current
        content = clean_text(response.text)

        if len(content) < 200:
            continue

        results.append(
            PageResult(
                title=title,
                url=current,
                section_type=section_type,
                content=content,
            )
        )

        for link in extract_links(soup, start_path):
            if link not in visited:
                queue.append(link)

        time.sleep(random.uniform(*DELAY_RANGE))

    return results


def save_results(results: List[PageResult]) -> None:
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8") as file:
        for result in results:
            file.write(
                json.dumps(
                    {
                        "title": result.title,
                        "url": result.url,
                        "type": result.section_type,
                        "content": result.content,
                    },
                    ensure_ascii=True,
                )
                + "\n"
            )


def main() -> None:
    robot_parser = load_robot_parser()
    all_results: List[PageResult] = []

    for path, section_type in SECTIONS.items():
        print(f"Crawling section '{section_type}' at {path} ...")
        section_results = crawl_section(path, section_type, robot_parser)
        print(f"  Found {len(section_results)} pages in {section_type}")
        all_results.extend(section_results)

    if not all_results:
        print("No pages were collected.")
        return

    save_results(all_results)

    counts = defaultdict(int)
    for result in all_results:
        counts[result.section_type] += 1

    print(f"Saved {len(all_results)} pages to {OUTPUT_PATH}")
    for section_type, count in counts.items():
        print(f"  {section_type}: {count}")


if __name__ == "__main__":
    main()
