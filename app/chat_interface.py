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


# Safeguard session state directly after imports
_initialize_ui_state()

st.set_page_config(
    page_title="The Christian Project",
    page_icon="✝️",
    layout="wide",
)

st.markdown("""
<style>
:root {
    color-scheme: only light;
}

html, body, .stApp {
    background-color: #f2ede3;
    color: #24190f;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
    font-size: 17px;
    line-height: 1.6;
}

.stApp {
    overflow-x: hidden;
}

a {
    color: #704c1f;
}

main .block-container {
    max-width: 1200px;
    padding: 1.2rem 1.75rem 9rem;
}

@media (min-width: 1024px) {
    main .block-container {
        padding: 2rem 3rem 10rem;
    }
}

section[data-testid="stSidebar"] {
    background: linear-gradient(180deg, #ece2d1 0%, #e2d5c1 100%);
    border-right: 1px solid rgba(46, 35, 25, 0.08);
}

section[data-testid="stSidebar"] > div {
    padding: 1.75rem 1.5rem 3rem;
}

section[data-testid="stSidebar"] h1,
section[data-testid="stSidebar"] h2,
section[data-testid="stSidebar"] h3,
section[data-testid="stSidebar"] p,
section[data-testid="stSidebar"] li,
section[data-testid="stSidebar"] a,
section[data-testid="stSidebar"] label {
    color: #2f2317;
}

section[data-testid="stSidebar"] h1 {
    font-size: 1.1rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 1.5rem;
}

section[data-testid="stSidebar"] .sidebar-section-title {
    font-size: 0.82rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #66543d;
    margin-top: 2.1rem;
    margin-bottom: 0.75rem;
}

section[data-testid="stSidebar"] button[data-testid="baseButton-primary"] {
    background: #4a3422;
    color: #f8f6f0;
    border-radius: 999px;
    border: none;
    padding: 0.75rem 1rem;
    font-weight: 600;
    box-shadow: 0 6px 18px rgba(56, 38, 24, 0.18);
}

section[data-testid="stSidebar"] button[data-testid="baseButton-primary"]:hover {
    background: #3c2a1c;
}

section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"] {
    background: rgba(255, 255, 255, 0.6);
    color: #2f2317;
    border-radius: 12px;
    border: 1px solid rgba(68, 51, 33, 0.12);
    padding: 0.55rem 0.75rem;
    justify-content: flex-start;
}

section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"]:hover {
    background: rgba(255, 255, 255, 0.82);
}

.recent-question-button span {
    overflow: hidden;
    text-overflow: ellipsis;
    display: block;
    width: 100%;
}

.chat-wrapper {
    background: rgba(255, 255, 255, 0.55);
    border-radius: 24px;
    padding: 1.75rem;
    box-shadow: 0 12px 32px rgba(0, 0, 0, 0.05);
    margin: 0 auto;
    max-width: 900px;
    width: 100%;
}

@media (max-width: 900px) {
    .chat-wrapper {
        background: transparent;
        box-shadow: none;
        padding: 1rem 0 0;
        max-width: 100%;
    }
}

.chat-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.5rem;
    margin-bottom: 1rem;
}

.chat-header-left {
    display: flex;
    align-items: center;
    gap: 0.75rem;
}

.chat-title-group h1 {
    font-size: 1.65rem;
    margin-bottom: 0.15rem;
    color: #2b1f13;
}

.chat-title-group p {
    margin: 0;
    color: #5c4a34;
    font-size: 0.95rem;
}

.chat-header-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
}

.preview-pill {
    background: rgba(70, 52, 33, 0.18);
    color: #4a3625;
    padding: 0.45rem 0.85rem;
    border-radius: 999px;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.08em;
}

.trust-panel {
    background: rgba(255, 255, 255, 0.75);
    border: 1px solid rgba(70, 52, 33, 0.18);
    border-radius: 16px;
    padding: 0.9rem 1.05rem;
    color: #463827;
    font-size: 0.9rem;
    margin-bottom: 1.5rem;
}

.trust-panel ul {
    list-style: none;
    padding-left: 0;
    margin: 0;
}

.trust-panel li {
    margin-bottom: 0.35rem;
}

.trust-panel li:last-child {
    margin-bottom: 0;
}

.chat-wrapper div[data-testid="stVerticalBlock"]:has(> div[data-testid="stChatMessage"]) {
    background: rgba(255, 255, 255, 0.6);
    border-radius: 18px;
    padding: 1.1rem 1.25rem;
    max-height: 70vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
}

.chat-wrapper div[data-testid="stVerticalBlock"]:has(> div[data-testid="stChatMessage"])::-webkit-scrollbar {
    width: 8px;
}

.chat-wrapper div[data-testid="stVerticalBlock"]:has(> div[data-testid="stChatMessage"])::-webkit-scrollbar-thumb {
    background-color: rgba(90, 70, 50, 0.3);
    border-radius: 999px;
}

.chat-scroll {
    background: rgba(255, 255, 255, 0.6);
    border-radius: 18px;
    padding: 1.1rem 1.25rem;
    max-height: 70vh;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
}

@media (max-width: 900px) {
    .chat-scroll {
        background: rgba(255, 255, 255, 0.35);
        padding: 0.5rem 0.25rem;
        max-height: none;
        overflow-y: visible;
    }
    .chat-wrapper div[data-testid="stVerticalBlock"]:has(> div[data-testid="stChatMessage"]) {
        background: rgba(255, 255, 255, 0.35);
        padding: 0.6rem 0.25rem;
        max-height: none;
        overflow-y: visible;
        gap: 0.9rem;
    }
}

.chat-scroll::-webkit-scrollbar {
    width: 8px;
}

.chat-scroll::-webkit-scrollbar-thumb {
    background-color: rgba(90, 70, 50, 0.3);
    border-radius: 999px;
}

.stChatMessage {
    background: transparent;
    padding: 0 !important;
}

.stChatMessage[data-testid="stChatMessage-User"] > div {
    margin-left: auto;
    max-width: 90%;
    background: #f6e4b5;
    border-radius: 18px;
    border: 1px solid rgba(148, 116, 62, 0.35);
    padding: 0.75rem 1rem;
    box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
}

.stChatMessage[data-testid="stChatMessage-Assistant"] > div {
    margin-right: auto;
    max-width: 90%;
    background: #fffaf1;
    border-radius: 18px;
    border: 1px solid rgba(126, 100, 66, 0.2);
    padding: 0.85rem 1.05rem;
    box-shadow: 0 6px 20px rgba(0, 0, 0, 0.07);
}

.stChatMessage .stMarkdown p {
    line-height: 1.68;
    color: #2b1f13 !important;
}

.feedback-wrapper p {
    font-size: 0.85rem;
    color: #5e4c34;
}

.doctrinal-footer {
    color: #6d5a43;
    font-size: 0.82rem;
    margin: 1rem 0 0.5rem;
    text-align: center;
}

.stChatInput {
    background: #2d2120;
    padding: 0.85rem 1.1rem 1.15rem;
    border-top-left-radius: 18px;
    border-top-right-radius: 18px;
    box-shadow: 0 -10px 30px rgba(0, 0, 0, 0.12);
    max-width: 900px;
    margin: 0 auto;
}

@media (min-width: 1024px) {
    .stChatInput {
        margin-left: calc(260px + 3.5rem);
        margin-right: 3.5rem;
    }
}

.stChatInput > div {
    gap: 0.65rem !important;
}

.stChatInput textarea {
    background: #fffdfa !important;
    border-radius: 14px !important;
    border: 1px solid rgba(255, 255, 255, 0.4) !important;
    color: #2d2120 !important;
    padding: 0.85rem 1rem !important;
    font-size: 1rem !important;
}

.stChatInput textarea::placeholder {
    color: rgba(80, 60, 45, 0.8) !important;
}

.stChatInput button[data-testid="baseButton-secondary"] {
    background: #d8b26f !important;
    border-radius: 999px !important;
    border: none !important;
    width: 88px;
    height: 46px !important;
    justify-content: center;
    position: relative;
}

.stChatInput button[data-testid="baseButton-secondary"] svg {
    display: none;
}

.stChatInput button[data-testid="baseButton-secondary"]::after {
    content: "Ask";
    font-weight: 600;
    color: #2d2120;
    font-size: 0.95rem;
}

.stChatInput button[data-testid="baseButton-secondary"]:hover {
    background: #c59a4b !important;
}

@media (max-width: 900px) {
    .chat-header {
        flex-direction: column;
        align-items: flex-start;
    }
    .chat-header-actions {
        width: 100%;
        justify-content: flex-end;
    }
    .stChatInput {
        margin: 0.75rem 0.75rem 0;
        max-width: calc(100% - 1.5rem);
        border-radius: 22px;
    }
}

@media (max-width: 600px) {
    .chat-title-group h1 {
        font-size: 1.4rem;
    }
    .chat-title-group p {
        font-size: 0.9rem;
    }
}

body.sidebar-open section[data-testid="stSidebar"] {
    transform: translateX(0);
    box-shadow: 2px 0 20px rgba(0, 0, 0, 0.2);
}

@media (max-width: 900px) {
    section[data-testid="stSidebar"] {
        position: fixed;
        top: 0;
        left: 0;
        bottom: 0;
        width: min(85%, 280px);
        transform: translateX(-100%);
        transition: transform 0.3s ease;
        z-index: 1000;
        padding-top: 1.5rem;
    }
    body.sidebar-open::after {
        content: "";
        position: fixed;
        inset: 0;
        background: rgba(27, 20, 14, 0.35);
        z-index: 999;
    }
    section[data-testid="stSidebar"] > div {
        height: 100%;
        overflow-y: auto;
    }
    .mobile-only {
        display: inline-flex !important;
    }
}

.mobile-only {
    display: none !important;
}

.hamburger-flag + div[data-testid="stButton"] button {
    background: transparent;
    border: 1px solid rgba(70, 52, 33, 0.2);
    color: #4a3625;
    border-radius: 12px;
    width: 46px;
    height: 46px;
    font-size: 1.2rem;
}

.hamburger-flag + div[data-testid="stButton"] {
    display: none;
}

@media (max-width: 900px) {
    .hamburger-flag + div[data-testid="stButton"] {
        display: block;
    }
}

.header-mobile-button-flag + div[data-testid="stButton"] {
    display: none;
}

@media (max-width: 900px) {
    .header-mobile-button-flag + div[data-testid="stButton"] {
        display: block;
    }
    .header-mobile-button-flag + div[data-testid="stButton"] button {
        background: rgba(255,255,255,0.25);
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.4);
        color: #fff;
        font-size: 0.85rem;
        padding: 0.4rem 0.9rem;
    }
}

.header-actions-container > div[data-testid="stButton"] {
    margin-right: 0.5rem;
}

.header-actions-container > div[data-testid="stButton"] button {
    background: rgba(74, 54, 34, 0.12);
    border-radius: 999px;
    border: 1px solid rgba(74, 54, 34, 0.25);
    color: #3a2a1b;
    font-size: 0.85rem;
    padding: 0.35rem 0.9rem;
}

@media (min-width: 901px) {
    .header-mobile-button-flag + div[data-testid="stButton"] {
        display: none !important;
    }
}

div[data-testid="stSidebarNav"] {
    display: none;
}
</style>

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
    st.session_state.pop("user_input", None)


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


def render_sidebar() -> None:
    sidebar = st.sidebar
    sidebar.markdown(
        """
        <div style="display:flex; align-items:center; gap:0.5rem; margin-bottom: 0.75rem;">
            <span style="font-size: 1.4rem;">✝️</span>
            <div>
                <div style="font-size:0.78rem; letter-spacing:0.22em; text-transform:uppercase; color:#6d5940;">The</div>
                <div style="font-family:'Georgia', serif; font-weight:600; font-size:1.1rem; margin-top:-0.2rem;">Christian Project</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )
    sidebar.markdown(
        "<p style='margin-top:-0.4rem; color:#6d5940;'>Faithful answers for curious hearts.</p>",
        unsafe_allow_html=True,
    )

    if sidebar.button(
        "New Chat",
        key="sidebar_new_chat",
        type="primary",
        use_container_width=True,
    ):
        reset_conversation()
        st.session_state.sidebar_open = False
        st.toast("🕊️ Conversation cleared. Ready for a new question.")
        st.experimental_rerun()

    sidebar.markdown(
        "<div class='sidebar-section-title'>Recent Questions</div>", unsafe_allow_html=True
    )

    recent_questions = st.session_state.get("recent_questions", [])
    if not recent_questions:
        sidebar.caption("No recent questions yet. Ask your first one!")
    else:
        for idx, question in enumerate(recent_questions):
            label = _format_recent_question_label(question)
            if sidebar.button(
                label,
                key=f"recent_question_{idx}",
                type="secondary",
                use_container_width=True,
            ):
                load_conversation_from_recent(question)
                st.experimental_rerun()

    sidebar.markdown(
        "<div class='sidebar-section-title'>Guidance</div>", unsafe_allow_html=True
    )
    if sidebar.button(
        "About & Guidance",
        key="open_about_modal",
        type="secondary",
        use_container_width=True,
    ):
        st.session_state.show_about_modal = True
        st.experimental_rerun()


def render_trust_panel() -> None:
    st.markdown(
        """
        <div class="trust-panel">
            <ul>
                <li>Please don’t include personal details (names, locations, etc.).</li>
                <li>Responses are grounded in Scripture and Lutheran teaching.</li>
                <li>For personal or urgent spiritual care, please talk with your pastor.</li>
            </ul>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_main_header() -> None:
    col_left, col_right = st.columns([7, 3], gap="medium")
    with col_left:
        btn_col, title_col = st.columns([1, 9], gap="small")
        with btn_col:
            st.markdown('<div class="hamburger-flag"></div>', unsafe_allow_html=True)
            if st.button("☰", key="toggle_sidebar", type="secondary"):
                st.session_state.sidebar_open = not st.session_state.get("sidebar_open", False)
        with title_col:
            st.markdown(
                """
                <div class="chat-header-left">
                    <div class="chat-title-group">
                        <h1>The Christian Project</h1>
                        <p>Faithful answers for curious hearts.</p>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )
    with col_right:
        action_btn_col, badge_col = st.columns([1.2, 1], gap="small")
        with action_btn_col:
            st.markdown('<div class="header-mobile-button-flag"></div>', unsafe_allow_html=True)
            if st.button("New Chat", key="header_new_chat", type="secondary"):
                reset_conversation()
                st.session_state.sidebar_open = False
                st.toast("🕊️ Conversation cleared. Ready for a new question.")
                st.experimental_rerun()
        with badge_col:
            st.markdown('<div class="preview-pill">Preview Build</div>', unsafe_allow_html=True)
    _sync_sidebar_body_class()


def render_doctrinal_footer() -> None:
    st.markdown(
        '<div class="doctrinal-footer">This assistant is not a substitute for pastoral care. Please speak with your pastor for personal guidance.</div>',
        unsafe_allow_html=True,
    )


def display_chat_history() -> None:
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
                    "👍 Helpful", key=f"feedback_pos_{idx}", use_container_width=True
                ):
                    record_feedback(
                        "positive",
                        message.get("question", ""),
                        message["content"],
                    )
                    st.toast("Thank you for your feedback!", icon="✅")
            with col2:
                if st.button(
                    "👎 Needs Review", key=f"feedback_neg_{idx}", use_container_width=True
                ):
                    record_feedback(
                        "negative",
                        message.get("question", ""),
                        message["content"],
                    )
                    st.toast("Feedback recorded for review.", icon="✍️")

    st.markdown(
        "<script>window.scrollTo(0, document.body.scrollHeight);</script>",
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
    TIMEOUT_MINUTES = 30
    now = time.time()

    if "last_activity" not in st.session_state:
        st.session_state.last_activity = now
    elif now - st.session_state.last_activity > TIMEOUT_MINUTES * 60:
        reset_conversation()
        st.info("Session cleared after a quiet pause. Ready whenever you are.")
        st.toast("🧹 Conversation cleared", icon="🕊️")
    st.session_state.last_activity = time.time()

    render_sidebar()

    chat_shell = st.container()
    with chat_shell:
        render_main_header()
        render_trust_panel()
        display_chat_history()
        render_doctrinal_footer()

    user_input = st.chat_input(
        "Ask a theological question...", key="user_input"
    )

    if user_input:
        process_input(user_input)
        st.session_state.pop("user_input", None)
        if hasattr(st, "rerun"):
            st.rerun()
        else:
            st.experimental_rerun()

    render_about_modal()


try:
    run_chat_interface()
    logging.info(
        "System update complete. UI now communicates safety, clarity, and ongoing pastoral oversight without changing theology."
    )
except Exception as exc:
    logging.exception("Unhandled error in interface: %s", exc)
    show_grace_message()
    st.stop()
