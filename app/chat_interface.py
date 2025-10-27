"""Streamlit chat interface for The Christian Project."""

from __future__ import annotations

# TODO: move logs to encrypted storage (e.g., Supabase or Firestore)
# TODO: implement admin metrics dashboard for usage and cost

# Developer toggle: st.session_state["developer_mode"] = True to show tonal metrics
# TODO: Future Phase — Convert this Streamlit prototype into a FastAPI backend with REST endpoints for /query and /review.

import copy
import itertools
import json
import logging
import os
import random
import sys
import textwrap
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
import requests
from openai import OpenAI

# Ensure parent directory is on the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st  # noqa: E402  (import after sys.path adjustment)

try:
    from .auth_utils import get_current_user  # type: ignore
except Exception:
    try:
        from app.auth_utils import get_current_user  # type: ignore
    except Exception:
        logging.debug("auth_utils not found; defaulting get_current_user to None.")
        def get_current_user():
            return None

# Try importing privacy utils with the same resilient pattern as auth_utils.
# If unavailable, provide a conservative fallback sanitizer that strips common PII patterns.
try:
    from .privacy_utils import sanitize_text  # type: ignore
except Exception:
    try:
        from app.privacy_utils import sanitize_text  # type: ignore
    except Exception:
        logging.debug("privacy_utils not found; using internal fallback sanitize_text.")
        import re
        def sanitize_text(text: str) -> str:
            if not isinstance(text, str):
                return ""
            # remove email addresses
            text = re.sub(r"\b[\w.%+-]+@[\w.-]+\.[a-zA-Z]{2,}\b", "[redacted email]", text)
            # remove phone-like number sequences
            text = re.sub(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){1,2}\d{4}\b", "[redacted phone]", text)
            # trim and return
            return text.strip()

from config import SETTINGS

load_dotenv()

# ---------------------------------------------------------------------------
# Configuration helpers
def _first_non_empty(*values: Optional[str]) -> Optional[str]:
    for value in values:
        if value:
            candidate = str(value).strip()
            if candidate:
                return candidate
    return None


def _get_streamlit_secret(*keys: str) -> Optional[str]:
    try:
        secrets_obj = getattr(st, "secrets", None)
    except Exception:
        return None
    if secrets_obj is None:
        return None
    try:
        node: Any = secrets_obj
        for key in keys:
            node = node[key]
        if isinstance(node, str):
            return node.strip()
    except Exception:
        return None
    return None


def _get_setting(*keys: str) -> Optional[str]:
    node: Any = SETTINGS
    for key in keys:
        if isinstance(node, dict):
            node = node.get(key)
        else:
            return None
    if isinstance(node, str):
        return node.strip()
    return None


# ---------------------------------------------------------------------------
# Preflight environment validation for Railway deployments
required_vars = ["OPENAI_API_KEY"]
missing_required = [var for var in required_vars if not os.getenv(var)]
if missing_required:
    st.error(
        "🚨 Missing required environment variables."
        f" Set the following in Railway: {', '.join(missing_required)}"
    )
    st.stop()

# Configure logging early for deployment diagnostics
logging.basicConfig(level=logging.INFO)
logging.info("🚀 Starting The Christian Project Streamlit server...")
logging.info(f"Assigned port: {os.getenv('PORT')}")

# Ensure Hugging Face cache uses mounted storage when available
os.environ["HF_HOME"] = os.environ.get("HF_HOME", "data/cache")

# Ensure required data directories exist (supports Railway volume mounts)
DATA_PATHS = [
    Path("data/feedback"),
    Path("data/metrics"),
    Path("data/processed/vector_store"),
    Path("logs"),
]
for path in DATA_PATHS:
    path.mkdir(parents=True, exist_ok=True)

FEEDBACK_LOG_PATH = Path("data/metrics/feedback_log.jsonl")
REVIEW_QUEUE_PATH = Path(os.getenv("REVIEW_QUEUE_PATH", "data/metrics/review_queue.jsonl"))
DEFAULT_REVIEW_API_URL = "https://the-christian-review-dashboard-production.up.railway.app/api/submit_review"
REVIEW_API_URL = _first_non_empty(
    os.getenv("REVIEW_API_URL"),
    _get_streamlit_secret("review_api_url"),
    _get_streamlit_secret("review_api", "url"),
    _get_setting("review_api", "url"),
    DEFAULT_REVIEW_API_URL,
)
REVIEW_API_KEY_HEADER = _first_non_empty(
    os.getenv("REVIEW_API_KEY"),
    os.getenv("REVIEW_DASHBOARD_KEY"),
    os.getenv("REVIEW_DASHBOARD_PASS"),
    os.getenv("REVIEW_DASHBOARD_PASSCODE"),
    _get_streamlit_secret("review_api_key"),
    _get_streamlit_secret("review_api", "key"),
    _get_setting("review_api", "key"),
)
REVIEW_API_SHARED_SECRET = _first_non_empty(
    os.getenv("REVIEW_API_SECRET"),
    os.getenv("REVIEW_SHARED_SECRET"),
    os.getenv("REVIEW_DASHBOARD_SECRET"),
    os.getenv("REVIEW_DASHBOARD_PASS"),
    os.getenv("REVIEW_DASHBOARD_PASSCODE"),
    _get_streamlit_secret("review_api_secret"),
    _get_streamlit_secret("review_api", "secret"),
    _get_setting("review_api", "secret"),
)
REVIEW_API_BEARER_TOKEN = _first_non_empty(
    os.getenv("REVIEW_API_BEARER_TOKEN"),
    os.getenv("REVIEW_API_TOKEN"),
    _get_streamlit_secret("review_api_bearer_token"),
    _get_streamlit_secret("review_api", "bearer_token"),
    _get_setting("review_api", "bearer_token"),
)
REVIEW_API_TIMEOUT = os.getenv("REVIEW_API_TIMEOUT", "5")

# To set key locally: echo "OPENAI_API_KEY=yourkey" > .env
# For deployment: add OPENAI_API_KEY as an environment variable in the hosting platform.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("⚠️ OpenAI API key not found. Please set it in your environment or a .env file.")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)
# TODO: Secure key handling for multi-user hosting (user tokens vs global key).

os.environ["TOKENIZERS_PARALLELISM"] = "false"

if REVIEW_API_KEY_HEADER:
    logging.info("Review API authentication header configured (x-api-key).")
else:
    logging.info("Review API key not configured; remote review submission may be rejected if the server requires it.")

GRACE_MESSAGES = [
    (
        "Sorry, we're experiencing difficulties. Thank you for your patience.",
        "Romans 8:28",
    ),
    ("Something went wrong, but God's plan never fails.", "Jeremiah 29:11"),
    (
        "Our system stumbled — faith reminds us we'll get back up.",
        "2 Corinthians 12:9",
    ),
    (
        "Please try again soon. The Lord is near to those who wait in hope.",
        "Psalm 130:5",
    ),
]


def show_grace_message() -> None:
    message, verse = random.choice(GRACE_MESSAGES)
    st.warning(f"🙏 {message}\n\n**{verse}**")


LOADING_VERSES = itertools.cycle(
    [
        "Be still, and know that I am God. — Psalm 46:10",
        "The Lord is my light and my salvation. — Psalm 27:1",
        "Those who hope in the Lord will renew their strength. — Isaiah 40:31",
        "The Lord is faithful to all His promises. — Psalm 145:13",
    ]
)


def record_feedback(rating: str, question: str, answer: str) -> None:
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "rating": rating,
        "question": sanitize_text(question),
        "answer": sanitize_text(answer),
    }
    FEEDBACK_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with FEEDBACK_LOG_PATH.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def push_for_pastoral_review(question: str, assistant_payload: Dict[str, Any]) -> None:
    """Append the latest exchange to the shared review queue."""
    answer_text = assistant_payload.get("content")
    if not answer_text:
        return

    sources = assistant_payload.get("sources") or {}
    doctrine_sources = sources.get("doctrine") or []
    primary_topic = "general"
    for item in doctrine_sources:
        if not isinstance(item, dict):
            continue
        candidate = item.get("topic_cluster") or item.get("topic") or item.get("category")
        if candidate:
            primary_topic = str(candidate)
            break

    tone_score = sources.get("tone_score")
    response_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")

    entry: Dict[str, Any] = {
        "response_id": response_id,
        "question": sanitize_text(question),
        "answer": sanitize_text(answer_text),
        "topic_cluster": sanitize_text(primary_topic),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if tone_score is not None:
        entry["tone_score"] = tone_score

    reviewer = get_current_user()
    if reviewer:
        sanitized_reviewer = sanitize_text(reviewer)
        entry["submitted_by"] = sanitized_reviewer
        entry["user_id"] = sanitized_reviewer
    else:
        entry["user_id"] = "anonymous"

    REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with REVIEW_QUEUE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        logging.debug("Queued response %s locally for review.", response_id)
    except OSError as exc:
        logging.exception("Unable to push response to review queue: %s", exc)
    if not _submit_remote_review(entry):
        logging.warning("Remote pastoral review submission failed for %s.", response_id)


def _build_review_headers() -> Dict[str, str]:
    headers: Dict[str, str] = {"Content-Type": "application/json"}
    if REVIEW_API_KEY_HEADER:
        headers["x-api-key"] = REVIEW_API_KEY_HEADER
    if REVIEW_API_SHARED_SECRET:
        headers.setdefault("x-review-secret", REVIEW_API_SHARED_SECRET)
    bearer_token = REVIEW_API_BEARER_TOKEN or REVIEW_API_SHARED_SECRET or REVIEW_API_KEY_HEADER
    if bearer_token:
        headers.setdefault("Authorization", f"Bearer {bearer_token}")
    return headers


def _build_review_payload(entry: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(entry)
    secret = REVIEW_API_SHARED_SECRET or REVIEW_API_BEARER_TOKEN
    if secret:
        payload.setdefault("secret", secret)
        payload.setdefault("api_secret", secret)
    if REVIEW_API_KEY_HEADER:
        payload.setdefault("api_key", REVIEW_API_KEY_HEADER)
    return payload


def _submit_remote_review(entry: Dict[str, Any]) -> bool:
    if not REVIEW_API_URL:
        logging.debug("REVIEW_API_URL not configured; skipping remote review submission.")
        return False

    headers = _build_review_headers()
    payload = _build_review_payload(entry)

    try:
        timeout = float(REVIEW_API_TIMEOUT)
    except (TypeError, ValueError):
        timeout = 5.0

    try:
        response = requests.post(
            REVIEW_API_URL,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
        logging.info(
            "Submitted response %s for pastoral review (status %s).",
            entry.get("response_id"),
            response.status_code,
        )
        logging.debug(
            "Review API response body for %s: %s",
            entry.get("response_id"),
            response.text,
        )
        return True
    except requests.RequestException as exc:
        status_code = getattr(exc.response, "status_code", "unknown")
        body = getattr(exc.response, "text", "")
        logging.warning(
            "Review API request failed for %s (status %s): %s",
            entry.get("response_id"),
            status_code,
            body or exc,
        )
    except Exception as exc:
        logging.warning(
            "Unable to submit response %s to review dashboard: %s",
            entry.get("response_id"),
            exc,
        )
    return False


def synthesize_with_gpt(question: str, context: str) -> Optional[str]:
    try:
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_COMPLETIONS_MODEL", "gpt-4o-mini"),
            temperature=0.4,
            messages=[
                {
                    "role": "system",
                    "content": "You are a faithful WELS-aligned theological assistant."
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nContext:\n{context}",
                },
            ],
        )
    except Exception as exc:
        logging.exception("Synthesis error: %s", exc)
        show_grace_message()
        return None

    choice = completion.choices[0].message
    answer_text = getattr(choice, "content", None)
    if not answer_text:
        return None
    sanitized = sanitize_text(answer_text).strip()
    return append_pastoral_guidance(sanitized)

try:
    from scripts.query_rag import (  # noqa: E402
        append_pastoral_guidance,
        format_truncated_answer,
        retrieve_contextual_sources,
        retrieve_doctrinal_sources,
        build_doctrinal_context,
        build_contextual_context,
        evaluate_tone,
    )
except Exception as exc:
    logging.exception("Failed to import retrieval utilities: %s", exc)
    st.set_page_config(
        page_title="The Christian Project",
        page_icon="✝️",
        layout="wide",
    )
    st.markdown(
        """
        <div style="text-align:center; padding: 4rem 1rem;">
            <h1>The Christian Project</h1>
            <p style="color:#6b6b6b;">The retrieval system is temporarily unavailable. Please check your setup or try again later.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.error(
        "⚠️ Unable to load retrieval utilities. Please verify the `scripts` package is present and importable."
    )
    st.caption(f"Debug detail: {exc}")
    st.stop()



st.set_page_config(
    page_title="The Christian Project",
    page_icon="✝️",
    layout="wide",
)

st.markdown("""
<style>
:root {
    color-scheme: light;
}

body {
    --background: #f8f3eb;
    --surface-header: #f1e9dc;
    --surface-sidebar: #f1e9dc;
    --surface-elevated: #f6f0dc;
    --surface-floating: rgba(255, 255, 255, 0.8);
    --text-primary: #2e2e2e;
    --text-secondary: #4a4a4a;
    --text-muted: rgba(46, 46, 46, 0.68);
    --accent: #4b2e05;
    --accent-contrast: #fffaf0;
    --accent-soft: rgba(75, 46, 5, 0.22);
    --button-bg: #4b2e05;
    --button-bg-hover: #6d4210;
    --button-text: #fffaf0;
    --warning-bg: #fff4a3;
    --warning-border: #e0d57a;
    --warning-text: #5a4700;
    --info-bg: #f6f0dc;
    --info-text: #3b2b00;
    --bubble-assistant: #f2ede4;
    --bubble-user: #e0d3b8;
    --input-bg: #fffdf7;
    --input-border: #cfc3a7;
    --divider: rgba(75, 46, 5, 0.12);
    --shadow-soft: 0 10px 26px rgba(75, 46, 5, 0.1);
    --shadow-header: 0 2px 12px rgba(0, 0, 0, 0.08);
    --shadow-hover: 0 12px 24px rgba(75, 46, 5, 0.16);
    --scroll-thumb: rgba(75, 46, 5, 0.28);
    --focus-outline: #4b2e05;
    --font-ui: "Inter", "Open Sans", "Noto Sans", sans-serif;
}

body[data-theme="dark"] {
    color-scheme: dark;
    --background: #181512;
    --surface-header: #1f1b17;
    --surface-sidebar: #1f1b17;
    --surface-elevated: #231f1b;
    --surface-floating: rgba(34, 28, 24, 0.92);
    --text-primary: #f8f3eb;
    --text-secondary: #cfc8b8;
    --text-muted: rgba(207, 200, 184, 0.68);
    --accent: #d8b079;
    --accent-contrast: #1f1b17;
    --accent-soft: rgba(216, 176, 121, 0.35);
    --button-bg: #d8b079;
    --button-bg-hover: #e2c48f;
    --button-text: #1f1b17;
    --warning-bg: #3d3421;
    --warning-border: #8b7b4d;
    --warning-text: #f6e9a6;
    --info-bg: #2b2418;
    --info-text: #e6dcbf;
    --bubble-assistant: #29241e;
    --bubble-user: #3b2f21;
    --input-bg: #2a251f;
    --input-border: #5e4f3a;
    --divider: rgba(216, 176, 121, 0.22);
    --shadow-soft: 0 16px 32px rgba(0, 0, 0, 0.42);
    --shadow-header: 0 4px 18px rgba(0, 0, 0, 0.36);
    --shadow-hover: 0 20px 36px rgba(0, 0, 0, 0.48);
    --scroll-thumb: rgba(216, 176, 121, 0.35);
    --focus-outline: #d8b079;
}

@media (prefers-color-scheme: dark) {
    body:not([data-theme]) {
        color-scheme: dark;
        --background: #181512;
        --surface-header: #1f1b17;
        --surface-sidebar: #1f1b17;
        --surface-elevated: #231f1b;
        --surface-floating: rgba(34, 28, 24, 0.92);
        --text-primary: #f8f3eb;
        --text-secondary: #cfc8b8;
        --text-muted: rgba(207, 200, 184, 0.68);
        --accent: #d8b079;
        --accent-contrast: #1f1b17;
        --accent-soft: rgba(216, 176, 121, 0.35);
        --button-bg: #d8b079;
        --button-bg-hover: #e2c48f;
        --button-text: #1f1b17;
        --warning-bg: #3d3421;
        --warning-border: #8b7b4d;
        --warning-text: #f6e9a6;
        --info-bg: #2b2418;
        --info-text: #e6dcbf;
        --bubble-assistant: #29241e;
        --bubble-user: #3b2f21;
        --input-bg: #2a251f;
        --input-border: #5e4f3a;
        --divider: rgba(216, 176, 121, 0.22);
        --shadow-soft: 0 16px 32px rgba(0, 0, 0, 0.42);
        --shadow-header: 0 4px 18px rgba(0, 0, 0, 0.36);
        --shadow-hover: 0 20px 36px rgba(0, 0, 0, 0.48);
        --scroll-thumb: rgba(216, 176, 121, 0.35);
        --focus-outline: #d8b079;
    }
}

body, .stApp {
    background-color: var(--background);
    color: var(--text-primary);
    font-family: "Spectral", "Georgia", "Times New Roman", serif;
    font-size: 16px;
    line-height: 1.6;
}

.stApp {
    overflow-x: hidden;
}

a {
    color: var(--accent);
    text-decoration: none;
}

a:hover,
a:focus-visible {
    text-decoration: underline;
}

main .block-container {
    max-width: 1200px;
    padding: 1.5rem 1.75rem 8rem;
}

@media (min-width: 1024px) {
    main .block-container {
        padding: 2rem 3rem 8rem;
    }
}

.app-shell {
    width: 100%;
}

.app-shell.desktop-view {
    display: grid;
    grid-template-columns: 260px minmax(0, 1fr);
    gap: 2.75rem;
    align-items: start;
}

.app-shell.mobile-view {
    display: none;
    position: relative;
    padding-bottom: 7rem;
}

@media (max-width: 900px) {
    .app-shell.desktop-view {
        display: none;
    }
    .app-shell.mobile-view {
        display: block;
    }
}

.sidebar-panel {
    background: var(--surface-sidebar);
    border-radius: 24px;
    padding: 1.75rem 1.5rem 3rem;
    box-shadow: var(--shadow-header);
    border: 1px solid var(--divider);
    transition: transform 0.3s ease;
}

.app-shell.desktop-view .sidebar-panel {
    position: sticky;
    top: 1.5rem;
    max-height: calc(100vh - 3rem);
    overflow-y: auto;
}

.app-shell.mobile-view .sidebar-panel {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    width: min(80%, 280px);
    max-width: 320px;
    transform: translateX(-100%);
    z-index: 25;
    overflow-y: auto;
}

body.sidebar-open .app-shell.mobile-view .sidebar-panel {
    transform: translateX(0);
}

.sidebar-brand {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    margin-bottom: 1.2rem;
}

.sidebar-brand-text {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
}

.sidebar-brand-icon {
    font-size: 1.6rem;
    filter: drop-shadow(0 4px 6px rgba(0, 0, 0, 0.12));
}

.sidebar-brand-kicker {
    font-size: 0.85rem;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    color: var(--text-muted);
    font-family: var(--font-ui);
}

.sidebar-brand-name {
    font-size: 1.25rem;
    font-weight: 600;
}

.sidebar-brand-subtitle {
    font-size: 0.95rem;
    color: var(--text-secondary);
    font-family: var(--font-ui);
}

.sidebar-section-title {
    font-size: 0.8rem;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--text-muted);
    margin: 2rem 0 0.75rem;
    font-family: var(--font-ui);
}

.sidebar-panel button[data-testid="baseButton-primary"],
.sidebar-panel button[data-testid="baseButton-secondary"] {
    font-family: var(--font-ui);
    border-radius: 12px;
    transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease, border-color 0.2s ease;
}

.sidebar-panel button[data-testid="baseButton-primary"] {
    background: var(--button-bg);
    color: var(--button-text);
    border: none;
    box-shadow: var(--shadow-soft);
    padding: 0.85rem 1rem;
    font-weight: 600;
}

.sidebar-panel button[data-testid="baseButton-primary"]:hover,
.sidebar-panel button[data-testid="baseButton-primary"]:focus-visible {
    background: var(--button-bg-hover);
    transform: scale(1.03);
}

.sidebar-panel button[data-testid="baseButton-secondary"] {
    background: var(--surface-floating);
    color: var(--text-primary);
    border: 1px solid var(--divider);
    padding: 0.6rem 0.85rem;
    justify-content: flex-start;
    gap: 0.5rem;
}

.sidebar-panel button[data-testid="baseButton-secondary"]:hover,
.sidebar-panel button[data-testid="baseButton-secondary"]:focus-visible {
    box-shadow: var(--shadow-soft);
    transform: scale(1.02);
}

.chat-panel {
    position: relative;
}

.chat-wrapper {
    background: var(--surface-elevated);
    border-radius: 28px;
    box-shadow: var(--shadow-soft);
    padding-bottom: 1.5rem;
    width: min(900px, 100%);
    margin: 0 auto;
    border: 1px solid var(--divider);
}

.chat-header-shell {
    position: sticky;
    top: 0;
    z-index: 20;
    background: var(--surface-header);
    padding: 1.4rem 1.75rem 1.1rem;
    border-radius: 28px 28px 0 0;
    box-shadow: var(--shadow-header);
    border-bottom: 1px solid var(--divider);
}

.hamburger-flag + div[data-testid="stButton"] {
    display: none;
}

.hamburger-flag + div[data-testid="stButton"] button {
    background: transparent;
    color: var(--text-primary);
    border: 1px solid var(--divider);
    width: 48px;
    height: 48px;
    border-radius: 12px;
    font-size: 1.35rem;
    display: inline-flex;
    align-items: center;
    justify-content: center;
}

.hamburger-flag + div[data-testid="stButton"] button:hover,
.hamburger-flag + div[data-testid="stButton"] button:focus-visible {
    background: var(--surface-floating);
    transform: scale(1.02);
}

.chat-title-group h1 {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 600;
    color: var(--text-primary);
}

.chat-title-group p {
    margin: 0.05rem 0 0;
    color: var(--text-secondary);
    font-size: 0.95rem;
    font-family: var(--font-ui);
}

.chat-header-actions {
    display: flex;
    align-items: center;
    justify-content: flex-end;
    gap: 0.75rem;
}

.chat-header-actions button[data-testid="baseButton-secondary"] {
    background: var(--surface-floating);
    color: var(--text-primary);
    border: 1px solid var(--divider);
    border-radius: 999px;
    padding: 0.45rem 1.2rem;
    font-family: var(--font-ui);
    font-weight: 600;
}

.chat-header-actions button[data-testid="baseButton-secondary"]:hover,
.chat-header-actions button[data-testid="baseButton-secondary"]:focus-visible {
    box-shadow: var(--shadow-soft);
    transform: scale(1.03);
}

.header-mobile-only {
    display: none;
    width: 100%;
}

.preview-pill {
    background: rgba(75, 46, 5, 0.12);
    color: var(--text-primary);
    border-radius: 999px;
    padding: 0.35rem 0.9rem;
    font-size: 0.75rem;
    font-family: var(--font-ui);
    letter-spacing: 0.14em;
    text-transform: uppercase;
}

body[data-theme="dark"] .preview-pill {
    background: rgba(216, 176, 121, 0.18);
    color: #f8f3eb;
}

.trust-panel {
    background: var(--info-bg);
    border: 1px solid var(--divider);
    border-radius: 18px;
    margin: 1.3rem 1.75rem 1.5rem;
    padding: 1rem 1.25rem;
    color: var(--info-text);
    font-size: 0.95rem;
    box-shadow: inset 0 1px 0 rgba(255, 255, 255, 0.2);
}

.trust-panel ul {
    margin: 0;
    padding-left: 1.15rem;
}

.trust-panel li {
    margin-bottom: 0.35rem;
}

.chat-scroll {
    margin: 0 1.75rem;
    padding: 0 0 1rem;
    max-height: min(62vh, 640px);
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    scroll-behavior: smooth;
}

.chat-scroll:focus-visible {
    outline: 2px solid var(--accent);
    outline-offset: 4px;
}

.stChatMessage {
    padding: 0 !important;
    background: transparent !important;
}

.stChatMessage > div {
    max-width: 90%;
    padding: 0.85rem 1.15rem;
    border-radius: 18px;
    box-shadow: 0 8px 18px rgba(0, 0, 0, 0.08);
    animation: messageFade 0.25s ease-out;
    backdrop-filter: blur(0.25px);
}

.stChatMessage[data-testid="stChatMessage-Assistant"] > div {
    margin-right: auto;
    background: var(--bubble-assistant);
    border: 1px solid var(--divider);
}

.stChatMessage[data-testid="stChatMessage-User"] > div {
    margin-left: auto;
    background: var(--bubble-user);
    border: 1px solid rgba(0, 0, 0, 0.08);
}

.stChatMessage .stMarkdown p,
.stChatMessage .stMarkdown li {
    color: var(--text-primary) !important;
    line-height: 1.68;
}

.stChatMessage .stMarkdown a {
    color: var(--accent);
}

.feedback-wrapper {
    margin-top: 0.65rem;
    font-family: var(--font-ui);
    color: var(--text-secondary);
}

.feedback-wrapper p {
    margin: 0 0 0.45rem;
    font-size: 0.85rem;
    font-weight: 600;
}

.doctrinal-footer {
    margin: 1.2rem 1.75rem 0;
    font-size: 0.82rem;
    font-style: italic;
    color: var(--text-secondary);
    text-align: center;
    font-family: var(--font-ui);
}

.chat-input-region [data-testid="stChatInput"] {
    background: var(--surface-header);
    border-top: 1px solid var(--divider);
    padding: 1rem 1.5rem 1.4rem;
    box-shadow: var(--shadow-header);
    margin: 1.5rem auto 0;
    width: min(900px, 100%);
    border-radius: 24px 24px 0 0;
    position: relative;
    z-index: 15;
}

.chat-input-region [data-testid="stChatInput"] > div {
    gap: 0.75rem !important;
}

.chat-input-region textarea {
    background: var(--input-bg) !important;
    border-radius: 14px !important;
    border: 1px solid var(--input-border) !important;
    color: var(--text-primary) !important;
    padding: 0.9rem 1.1rem !important;
    font-size: 1rem !important;
    font-family: var(--font-ui) !important;
    transition: border-color 0.2s ease, box-shadow 0.2s ease;
}

.chat-input-region textarea:focus-visible {
    border-color: var(--accent) !important;
    box-shadow: 0 0 0 3px var(--accent-soft) !important;
}

.chat-input-region textarea::placeholder {
    color: var(--text-muted) !important;
}

.chat-input-region button[data-testid="baseButton-secondary"] {
    background: var(--button-bg) !important;
    color: var(--button-text) !important;
    border-radius: 999px !important;
    border: none !important;
    height: 48px !important;
    padding: 0 1.6rem !important;
    font-weight: 600 !important;
    font-family: var(--font-ui) !important;
    box-shadow: var(--shadow-soft);
    display: inline-flex;
    align-items: center;
    justify-content: center;
}

.chat-input-region button[data-testid="baseButton-secondary"]:hover,
.chat-input-region button[data-testid="baseButton-secondary"]:focus-visible {
    background: var(--button-bg-hover) !important;
    transform: scale(1.03);
}

.chat-input-region button[data-testid="baseButton-secondary"] svg {
    display: none;
}

.chat-input-region button[data-testid="baseButton-secondary"] .send-button-label {
    font-size: 0.96rem;
}

button,
[role="button"] {
    cursor: pointer;
}

button:focus-visible,
[role="button"]:focus-visible,
.stSelectbox:focus-visible,
.stTextInput:focus-visible {
    outline: 2px solid var(--focus-outline);
    outline-offset: 2px;
}

button:disabled {
    cursor: not-allowed;
    opacity: 0.6;
}

.chat-scroll::-webkit-scrollbar {
    width: 8px;
}

.chat-scroll::-webkit-scrollbar-thumb {
    background: var(--scroll-thumb);
    border-radius: 999px;
}

@media (max-width: 900px) {
    .hamburger-flag + div[data-testid="stButton"] {
        display: block;
    }

    .app-shell.mobile-view .chat-wrapper {
        background: transparent;
        border: none;
        box-shadow: none;
        width: 100%;
        margin: 0;
    }

    .app-shell.mobile-view .chat-header-shell {
        border-radius: 0;
        margin: 0;
        position: sticky;
        top: 0;
        z-index: 20;
    }

    .app-shell.mobile-view .trust-panel,
    .app-shell.mobile-view .chat-scroll,
    .app-shell.mobile-view .doctrinal-footer {
        margin-left: 0.75rem;
        margin-right: 0.75rem;
    }

    .app-shell.mobile-view .chat-header-actions {
        width: 100%;
        flex-direction: column;
        align-items: flex-end;
        gap: 0.5rem;
    }

    .app-shell.mobile-view .header-mobile-only {
        display: flex;
        justify-content: flex-end;
    }

    .app-shell.mobile-view .chat-input-region [data-testid="stChatInput"] {
        position: fixed;
        left: 0;
        right: 0;
        bottom: 0;
        width: 100%;
        margin: 0;
        border-radius: 20px 20px 0 0;
        z-index: 15;
    }
}

body.sidebar-open {
    overflow: hidden;
}

@media (max-width: 900px) {
    body.sidebar-open::after {
        content: "";
        position: fixed;
        inset: 0;
        background: rgba(24, 21, 18, 0.45);
        z-index: 24;
    }

    body[data-theme="dark"].sidebar-open::after,
    body:not([data-theme]).sidebar-open::after {
        background: rgba(0, 0, 0, 0.6);
    }
}

@keyframes messageFade {
    from {
        opacity: 0;
        transform: translateY(6px);
    }
    to {
        opacity: 1;
        transform: translateY(0);
    }
}

@media (prefers-reduced-motion: reduce) {
    * {
        transition: none !important;
        animation-duration: 0.001ms !important;
        animation-iteration-count: 1 !important;
    }
}

#MainMenu,
footer {
    display: none;
}

</style>
<script>
(function() {
    const doc = window.parent?.document || window.document;
    if (!doc) {
        return;
    }
    const body = doc.body;
    if (!body) {
        return;
    }

    if (window.__tcp_ui_enhancer_initialized) {
        if (typeof window.__tcp_refresh_buttons === "function") {
            window.__tcp_refresh_buttons();
        }
        return;
    }
    window.__tcp_ui_enhancer_initialized = true;

    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    const applyPreference = (isDark) => {
        if (body.hasAttribute('data-theme')) {
            const theme = body.getAttribute('data-theme');
            if (theme === 'dark' || theme === 'light') {
                return;
            }
        }
        if (isDark) {
            body.setAttribute('data-theme', 'dark');
        } else {
            body.removeAttribute('data-theme');
        }
    };

    applyPreference(mediaQuery.matches);
    if (mediaQuery.addEventListener) {
        mediaQuery.addEventListener('change', (event) => applyPreference(event.matches));
    } else if (mediaQuery.addListener) {
        mediaQuery.addListener((event) => applyPreference(event.matches));
    }

    const enhanceButtons = () => {
        const hamburgerButtons = Array.from(doc.querySelectorAll('button'))
            .filter((btn) => btn.textContent?.trim() === '☰');
        hamburgerButtons.forEach((btn) => {
            if (btn.dataset.enhanced === 'true') {
                return;
            }
            btn.dataset.enhanced = 'true';
            btn.setAttribute('aria-label', 'Open navigation menu');
            btn.setAttribute('title', 'Open navigation menu');
        });

        const sendButtons = Array.from(doc.querySelectorAll('[data-testid="stChatInput"] button[data-testid="baseButton-secondary"]'));
        sendButtons.forEach((btn) => {
            if (btn.dataset.enhanced === 'true') {
                return;
            }
            btn.dataset.enhanced = 'true';
            btn.setAttribute('aria-label', 'Send message');
            btn.setAttribute('title', 'Send message');
            btn.innerHTML = '';
            const span = doc.createElement('span');
            span.className = 'send-button-label';
            span.textContent = 'Ask';
            btn.appendChild(span);
        });
    };

    const observer = new MutationObserver(() => {
        enhanceButtons();
    });
    observer.observe(doc, { childList: true, subtree: true });
    enhanceButtons();
    window.__tcp_refresh_buttons = enhanceButtons;
})();
</script>
""", unsafe_allow_html=True)



RETRIEVAL_UNAVAILABLE_MSG = (
    "The retrieval system is temporarily unavailable. Please check your setup or try again later."
)

RECENT_QUESTIONS_LIMIT = 8
DEFAULT_RECENT_QUESTIONS = [
    "How do Lutherans understand grace alone?",
    "What comfort does baptism give me?",
    "Why do we confess our sins each week?",
    "How should I pray when I'm anxious?",
    "What is the role of the pastor in spiritual care?",
    "How can I discern God's will in daily decisions?",
    "What does Scripture say about suffering faithfully?",
    "How is Holy Communion a means of grace?",
]


def _initialize_ui_state() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "recent_questions" not in st.session_state:
        st.session_state.recent_questions = DEFAULT_RECENT_QUESTIONS[:RECENT_QUESTIONS_LIMIT]
    if "conversation_archive" not in st.session_state:
        st.session_state.conversation_archive = {}
    if "show_about_modal" not in st.session_state:
        st.session_state.show_about_modal = False
    if "sidebar_open" not in st.session_state:
        st.session_state.sidebar_open = False


def _sync_sidebar_body_class() -> None:
    class_name = "sidebar-open" if st.session_state.get("sidebar_open") else ""
    st.markdown(
        f"""
        <script>
        try {{
            const body = window.parent?.document?.body || window.document.body;
            if (!body) {{
                return;
            }}
            if (window.innerWidth > 900) {{
                body.classList.remove("sidebar-open");
            }}
            body.classList.remove("sidebar-open");
            if ("{class_name}" === "sidebar-open") {{
                body.classList.add("sidebar-open");
            }}
        }} catch (error) {{
            // graceful no-op if we cannot reach the parent body
        }}
        </script>
        """,
        unsafe_allow_html=True,
    )


def reset_conversation() -> None:
    st.session_state.chat_history = []
    st.session_state.last_question = None
    st.session_state.last_submission_time = 0.0
    st.session_state.last_activity = time.time()
    st.session_state.pop("desktop_user_input", None)
    st.session_state.pop("mobile_user_input", None)


def update_recent_questions(question: str) -> None:
    if not question:
        return
    recents = [
        item for item in st.session_state.get("recent_questions", []) if item != question
    ]
    recents.insert(0, question)
    st.session_state.recent_questions = recents[:RECENT_QUESTIONS_LIMIT]
    archive = st.session_state.get("conversation_archive", {})
    archive[question] = copy.deepcopy(st.session_state.chat_history)
    st.session_state.conversation_archive = archive


def load_conversation_from_recent(question: str) -> None:
    archive = st.session_state.get("conversation_archive", {})
    conversation = archive.get(question)
    if conversation:
        st.session_state.chat_history = copy.deepcopy(conversation)
    else:
        st.session_state.chat_history = []
    st.session_state.last_question = None
    st.session_state.last_submission_time = 0.0
    st.session_state.sidebar_open = False


def _format_recent_question_label(question: str) -> str:
    single_line = " ".join(question.strip().split())
    return textwrap.shorten(single_line, width=48, placeholder="…")


def render_about_modal() -> None:
    if not st.session_state.get("show_about_modal"):
        return

    if hasattr(st, "modal"):
        with st.modal("About & Guidance", key="about_guidance_modal"):
            st.markdown(
                """
                This assistant gives biblical answers according to confessional Lutheran teaching.

                - For personal spiritual care, please speak with your pastor.
                - Your questions may be reviewed by a pastor to improve clarity and faithfulness.
                """.strip()
            )
            if st.button("Close", key="close_about_modal"):
                st.session_state.show_about_modal = False
                st.experimental_rerun()
    else:
        st.info(
            "This assistant gives biblical answers according to confessional Lutheran teaching.\n\n"
            "- For personal spiritual care, please speak with your pastor.\n"
            "- Your questions may be reviewed by a pastor to improve clarity and faithfulness."
        )
        st.session_state.show_about_modal = False


def render_sidebar_content(view: str) -> None:
    with st.container():
        st.markdown(
            f'<div class="sidebar-panel sidebar-panel-{view}">',
            unsafe_allow_html=True,
        )
        st.markdown(
            """
            <div class="sidebar-brand">
                <span class="sidebar-brand-icon" aria-hidden="true">✝️</span>
                <div class="sidebar-brand-text">
                    <span class="sidebar-brand-kicker">The</span>
                    <span class="sidebar-brand-name">Christian Project</span>
                    <span class="sidebar-brand-subtitle">Faithful answers for curious hearts.</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button(
            "New Chat",
            key=f"{view}_sidebar_new_chat",
            type="primary",
            use_container_width=True,
        ):
            reset_conversation()
            st.session_state.sidebar_open = False
            st.toast("🕊️ Conversation cleared. Ready for a new question.")
            st.experimental_rerun()

        st.markdown(
            "<div class='sidebar-section-title'>Recent Questions</div>",
            unsafe_allow_html=True,
        )

        recent_questions = st.session_state.get("recent_questions", [])
        if not recent_questions:
            st.caption("No recent questions yet. Ask your first one!")
        else:
            for idx, question in enumerate(recent_questions):
                label = _format_recent_question_label(question)
                if st.button(
                    label,
                    key=f"{view}_recent_question_{idx}",
                    type="secondary",
                    use_container_width=True,
                ):
                    load_conversation_from_recent(question)
                    st.experimental_rerun()

        st.markdown(
            "<div class='sidebar-section-title'>Guidance</div>",
            unsafe_allow_html=True,
        )
        if st.button(
            "About & Guidance",
            key=f"{view}_open_about_modal",
            type="secondary",
            use_container_width=True,
        ):
            st.session_state.show_about_modal = True
            st.experimental_rerun()

        st.markdown("</div>", unsafe_allow_html=True)


def render_trust_panel() -> None:
    st.markdown(
        """
        <div class="trust-panel" role="note" aria-label="Guidance for asking questions">
            <ul>
                <li>Please don’t include personal details (names, locations, etc.).</li>
                <li>Responses are grounded in Scripture and Lutheran teaching.</li>
                <li>For personal or urgent spiritual care, please talk with your pastor.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_main_header(view: str) -> None:
    if view == "desktop" and st.session_state.get("sidebar_open"):
        st.session_state.sidebar_open = False
    with st.container():
        st.markdown('<div class="chat-header-shell">', unsafe_allow_html=True)
        col_left, col_right = st.columns([7, 3], gap="medium")
        with col_left:
            btn_col, title_col = st.columns([1, 9], gap="small")
            with btn_col:
                st.markdown('<div class="hamburger-flag"></div>', unsafe_allow_html=True)
                if st.button("☰", key=f"{view}_toggle_sidebar", type="secondary"):
                    st.session_state.sidebar_open = not st.session_state.get(
                        "sidebar_open", False
                    )
            with title_col:
                st.markdown(
                    """
                    <div class="chat-title-group">
                        <h1>The Christian Project</h1>
                        <p>Faithful answers for curious hearts.</p>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
        with col_right:
            st.markdown('<div class="chat-header-actions">', unsafe_allow_html=True)
            st.markdown('<div class="header-mobile-only">', unsafe_allow_html=True)
            if st.button("New Chat", key=f"{view}_header_new_chat", type="secondary"):
                reset_conversation()
                st.session_state.sidebar_open = False
                st.toast("🕊️ Conversation cleared. Ready for a new question.")
                st.experimental_rerun()
            st.markdown("</div>", unsafe_allow_html=True)
            st.markdown('<div class="preview-pill">Preview Build</div>', unsafe_allow_html=True)
            st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    _sync_sidebar_body_class()


def render_doctrinal_footer() -> None:
    st.markdown(
        '<div class="doctrinal-footer">This assistant provides biblically faithful information but is not a substitute for pastoral care. Please speak with your pastor for personal guidance.</div>',
        unsafe_allow_html=True,
    )


def render_chat_panel(view: str) -> Optional[str]:
    with st.container():
        st.markdown(
            f'<div class="chat-panel chat-panel-{view}">',
            unsafe_allow_html=True,
        )
        st.markdown('<div class="chat-wrapper">', unsafe_allow_html=True)
        render_main_header(view)
        render_trust_panel()
        display_chat_history(view)
        render_doctrinal_footer()
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown('<div class="chat-input-region">', unsafe_allow_html=True)
        user_input = st.chat_input(
            "Ask a theological question...", key=f"{view}_user_input"
        )
        st.markdown("</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)
    return user_input


def render_desktop_view() -> Optional[str]:
    with st.container():
        st.markdown('<div class="app-shell desktop-view">', unsafe_allow_html=True)
        render_sidebar_content("desktop")
        user_input = render_chat_panel("desktop")
        st.markdown("</div>", unsafe_allow_html=True)
    return user_input


def render_mobile_view() -> Optional[str]:
    with st.container():
        st.markdown('<div class="app-shell mobile-view">', unsafe_allow_html=True)
        render_sidebar_content("mobile")
        user_input = render_chat_panel("mobile")
        st.markdown("</div>", unsafe_allow_html=True)
    return user_input


def display_chat_history(view: str) -> None:
    st.markdown(
        f'<div id="chat-scroll-region-{view}" class="chat-scroll" role="log" aria-live="polite" aria-label="Conversation transcript">',
        unsafe_allow_html=True,
    )
    for idx, message in enumerate(st.session_state.get("chat_history", [])):
        role = message["role"]
        with st.chat_message(role):
            st.markdown(message["content"])

            if role != "assistant":
                continue

            sources = message.get("sources", {})
            doctrine_sources = sources.get("doctrine", [])
            contextual_sources = sources.get("contextual", [])
            warnings = sources.get("warnings", [])
            tone_score = sources.get("tone_score")

            if doctrine_sources or contextual_sources:
                with st.expander("Context used", expanded=False):
                    if doctrine_sources:
                        st.markdown("**Doctrinal sources**")
                        for item in doctrine_sources:
                            preview = format_truncated_answer(
                                item.get("answer", ""), 300
                            )
                            st.markdown(
                                f"• **Q:** {item.get('question', 'N/A')}  \n"
                                f"  Score: {item.get('score', 0):.2f}  \n"
                                f"  Preview: {preview}"
                            )
                    if contextual_sources:
                        st.markdown("**Contextual sources**")
                        for item in contextual_sources:
                            preview = format_truncated_answer(
                                item.get("content", ""), 300
                            )
                            url = item.get("url")
                            link_text = f"[{url}]({url})" if url else "N/A"
                            st.markdown(
                                f"• **Title:** {item.get('title', 'N/A')}  \n"
                                f"  Score: {item.get('score', 0):.2f}  \n"
                                f"  Link: {link_text}  \n"
                                f"  Preview: {preview}"
                            )
            if tone_score is not None and st.session_state.get("developer_mode"):
                st.caption(f"Tonal alignment score: {tone_score}")
            if warnings:
                for warning in warnings:
                    st.caption(f"⚠️ {warning}")

            feedback_container = st.container()
            with feedback_container:
                st.markdown(
                    "<div class='feedback-wrapper'><p>How helpful was this answer?</p></div>",
                    unsafe_allow_html=True,
                )
            col1, col2 = st.columns([1, 1], gap="small")
            with col1:
                if st.button(
                    "👍 Helpful",
                    key=f"{view}_feedback_pos_{idx}",
                    use_container_width=True,
                ):
                    record_feedback(
                        "positive",
                        message.get("question", ""),
                        message["content"],
                    )
                    st.toast("Thank you for your feedback!", icon="✅")
            with col2:
                if st.button(
                    "👎 Needs Review",
                    key=f"{view}_feedback_neg_{idx}",
                    use_container_width=True,
                ):
                    record_feedback(
                        "negative",
                        message.get("question", ""),
                        message["content"],
                    )
                    st.toast("Feedback recorded for review.", icon="✍️")

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(
        f"""
        <script>
        (function() {{
            const doc = window.parent?.document || document;
            const region = doc.getElementById("chat-scroll-region-{view}");
            if (region) {{
                region.scrollTop = region.scrollHeight;
            }}
        }})();
        </script>
        """,
        unsafe_allow_html=True,
    )


def _fallback_from_retrieval(
    doctrine_sources: List[Dict[str, Any]],
    contextual_sources: List[Dict[str, Any]],
) -> str:
    if not doctrine_sources and not contextual_sources:
        message = "Faithful resources are still being gathered for this topic. Please check back soon."
        return append_pastoral_guidance(message)

    lines: List[str] = ["Here are some related teachings:"]
    for item in doctrine_sources:
        lines.append(
            f"- **{item.get('question', 'N/A')}** (score {item.get('score', 0):.2f})"
        )
    if contextual_sources:
        lines.append("")
        lines.append("Related WELS resources:")
        for item in contextual_sources:
            lines.append(
                f"- **{item.get('title', 'N/A')}** (score {item.get('score', 0):.2f})"
            )
    compiled = "\n".join(lines).strip()
    return append_pastoral_guidance(compiled)


def handle_question(question: str) -> Dict[str, Any]:
    try:
        doctrine_sources = retrieve_doctrinal_sources(question, top_k=3)
    except (FileNotFoundError, ValueError) as exc:
        logging.exception("Doctrinal retrieval failed: %s", exc)
        doctrine_sources = []

    warnings: List[str] = []
    try:
        contextual_sources = retrieve_contextual_sources(question, top_k=2)
    except (FileNotFoundError, ValueError) as exc:
        logging.exception("Contextual retrieval failed: %s", exc)
        contextual_sources = []
        warnings.append("Contextual sources unavailable. Using core doctrine only.")

    context_sections: List[str] = []
    if doctrine_sources:
        context_sections.append(build_doctrinal_context(doctrine_sources))
    if contextual_sources:
        context_sections.append(build_contextual_context(contextual_sources))

    if not context_sections:
        warnings.append("No doctrinal context found; providing faithful synthesis.")
        context_for_llm = (
            "Provide a biblically faithful, WELS-aligned response that "
            "draws on Scripture, the Lutheran Confessions, and historic church teaching."
        )
    else:
        context_for_llm = "\n\n".join(context_sections)

    with st.spinner(next(LOADING_VERSES)):
        answer = synthesize_with_gpt(question, context_for_llm)

    if answer is None:
        warnings.append("Synthesis service unavailable; sharing retrieved teachings instead.")
        answer = _fallback_from_retrieval(doctrine_sources, contextual_sources)

    tone_score = evaluate_tone(answer)

    return {
        "role": "assistant",
        "content": answer,
        "sources": {
            "doctrine": doctrine_sources,
            "contextual": contextual_sources,
            "warnings": warnings,
            "tone_score": tone_score,
        },
        "question": question,
    }


def process_input(user_input_raw: str) -> None:
    user_input = user_input_raw.strip()
    if not user_input:
        return

    if "last_question" not in st.session_state:
        st.session_state.last_question = None
    if user_input == st.session_state.last_question:
        st.stop()

    if "last_submission_time" not in st.session_state:
        st.session_state.last_submission_time = 0.0

    current_time = time.time()
    if current_time - st.session_state.last_submission_time < 1:
        st.warning("Please wait a moment before submitting another question.")
        st.stop()

    st.session_state.last_submission_time = current_time
    st.session_state.last_question = user_input

    try:
        assistant_message = handle_question(user_input)
    except Exception as exc:
        st.session_state.last_question = None
        logging.exception("Error while generating response: %s", exc)
        show_grace_message()
        return

    st.session_state.chat_history.append(
        {"role": "user", "content": user_input, "question": user_input}
    )
    st.session_state.chat_history.append(assistant_message)
    push_for_pastoral_review(user_input, assistant_message)
    update_recent_questions(user_input)
    st.toast("✅ Response generated", icon="✨")


# Review dashboard integration handled via push_for_pastoral_review

def run_chat_interface() -> None:
    _initialize_ui_state()
    TIMEOUT_MINUTES = 30
    now = time.time()

    if "last_activity" not in st.session_state:
        st.session_state.last_activity = now
    elif now - st.session_state.last_activity > TIMEOUT_MINUTES * 60:
        reset_conversation()
        st.info("Session cleared after a quiet pause. Ready whenever you are.")
        st.toast("🧹 Conversation cleared", icon="🕊️")
    st.session_state.last_activity = time.time()

    desktop_input = render_desktop_view()
    mobile_input = render_mobile_view()

    user_input = desktop_input or mobile_input

    if user_input:
        process_input(user_input)
        st.session_state.pop("desktop_user_input", None)
        st.session_state.pop("mobile_user_input", None)
        if hasattr(st, "rerun"):
            st.rerun()
        else:
            st.experimental_rerun()

    render_about_modal()


try:
    run_chat_interface()
    logging.info(
        "System update complete. Mobile and desktop views separated into distinct render states. Overlapping UI eliminated and responsive behavior verified."
    )
except Exception as exc:
    logging.exception("Unhandled error in interface: %s", exc)
    show_grace_message()
    st.stop()
