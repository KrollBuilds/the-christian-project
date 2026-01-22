"""Streamlit chat interface for The Christian Project."""

from __future__ import annotations

# TODO: move logs to encrypted storage (e.g., Supabase or Firestore)
# TODO: implement admin metrics dashboard for usage and cost

# Developer toggle: st.session_state["developer_mode"] = True to show tonal metrics
# TODO: Future Phase — Convert this Streamlit prototype into a FastAPI backend with REST endpoints for /query and /review.

import base64
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
from io import BytesIO

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

PUBLIC_ASSETS_DIR = Path(PROJECT_ROOT) / "public"
ICONS_DIR = PUBLIC_ASSETS_DIR / "icons"
STATIC_ICONS_DIR = Path(PROJECT_ROOT) / ".streamlit" / "static" / "icons"


def _find_icon_path(filename: str) -> Path:
    for directory in (STATIC_ICONS_DIR, ICONS_DIR):
        candidate = directory / filename
        if candidate.exists():
            return candidate
    return ICONS_DIR / filename


LOGO_32_PATH = _find_icon_path("logo-32.png")
LOGO_192_PATH = _find_icon_path("logo-192.png")
LOGO_512_PATH = _find_icon_path("logo-512.png")
SERVICE_WORKER_PATH = PUBLIC_ASSETS_DIR / "service-worker.js"


def _read_bytes(path: Path) -> Optional[bytes]:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        return None


def _to_data_uri(data: Optional[bytes]) -> Optional[str]:
    if not data:
        return None
    encoded = base64.b64encode(data).decode("utf-8")
    return f"data:image/png;base64,{encoded}"


LOGO_32_BYTES = _read_bytes(LOGO_32_PATH)
LOGO_192_BYTES = _read_bytes(LOGO_192_PATH)
LOGO_512_BYTES = _read_bytes(LOGO_512_PATH)

LOGO_SMALL_DATA_URI = _to_data_uri(LOGO_32_BYTES or LOGO_192_BYTES)
LOGO_PRIMARY_DATA_URI = _to_data_uri(LOGO_192_BYTES)
LOGO_LARGE_DATA_URI = _to_data_uri(LOGO_512_BYTES or LOGO_192_BYTES)


def _page_icon() -> Any:
    if LOGO_192_BYTES:
        return BytesIO(LOGO_192_BYTES)
    return "✝"

SERVICE_WORKER_INLINE = (
    SERVICE_WORKER_PATH.read_text(encoding="utf-8") if SERVICE_WORKER_PATH.exists() else ""
)

PWA_ICON_PATHS = {
    "favicon": "/static/icons/logo-32.png",
    "icon_192": "/static/icons/logo-192.png",
    "icon_512": "/static/icons/logo-512.png",
    "manifest": "/manifest.json",
    "service_worker": "/service-worker.js",
}


def _resolve_logo_src(size: str = "primary") -> str:
    if size == "small":
        return LOGO_SMALL_DATA_URI or PWA_ICON_PATHS["favicon"]
    if size == "large":
        return LOGO_LARGE_DATA_URI or PWA_ICON_PATHS["icon_512"]
    return LOGO_PRIMARY_DATA_URI or PWA_ICON_PATHS["icon_192"]


def inject_pwa_metadata() -> None:
    """Ensure manifest, icons, and service worker registration are wired into the document head."""
    if st.session_state.get("_tcp_pwa_metadata_injected"):
        return
    st.session_state["_tcp_pwa_metadata_injected"] = True

    manifest_href = json.dumps(PWA_ICON_PATHS["manifest"])
    icon32_href = json.dumps(PWA_ICON_PATHS["favicon"])
    icon192_href = json.dumps(PWA_ICON_PATHS["icon_192"])
    icon512_href = json.dumps(PWA_ICON_PATHS["icon_512"])
    service_worker_href = json.dumps(PWA_ICON_PATHS["service_worker"])
    inline_service_worker = (
        json.dumps(SERVICE_WORKER_INLINE.strip())
        if SERVICE_WORKER_INLINE.strip()
        else "null"
    )

    script_template = """
<script>
(function() {
    if (window.__tcpPwaInjected) {
        return;
    }
    window.__tcpPwaInjected = true;
    const head = document.head || document.getElementsByTagName('head')[0];
    if (!head) {
        return;
    }
    const linkDefinitions = [
        { rel: 'manifest', href: __MANIFEST__ },
        { rel: 'icon', href: __ICON32__, sizes: '32x32', type: 'image/png' },
        { rel: 'icon', href: __ICON192__, sizes: '192x192', type: 'image/png' },
        { rel: 'apple-touch-icon', href: __ICON512__, sizes: '512x512', type: 'image/png' }
    ];
    linkDefinitions.forEach((def) => {
        if (!def.href) {
            return;
        }
        const selector = `link[rel='${def.rel}'][href='${def.href}']`;
        let link = head.querySelector(selector);
        if (!link) {
            link = document.createElement('link');
            link.rel = def.rel;
            head.appendChild(link);
        }
        if (def.href) {
            link.href = def.href;
        }
        if (def.sizes) {
            link.sizes = def.sizes;
        }
        if (def.type) {
            link.type = def.type;
        }
    });
    const metaPairs = [
        ['theme-color', '#4b2e05'],
        ['apple-mobile-web-app-capable', 'yes'],
        ['apple-mobile-web-app-status-bar-style', 'black-translucent'],
        ['apple-mobile-web-app-title', 'The Christian Project'],
        ['description', 'Faithful answers for curious hearts.'],
        ['viewport', 'width=device-width, initial-scale=1.0, viewport-fit=cover, maximum-scale=1.0, user-scalable=no']
    ];
    metaPairs.forEach(([name, content]) => {
        let meta = head.querySelector(`meta[name='${name}']`);
        if (!meta) {
            meta = document.createElement('meta');
            meta.name = name;
            head.appendChild(meta);
        }
        meta.content = content;
    });
    if ('serviceWorker' in navigator) {
        const register = (url) => navigator.serviceWorker.register(url).catch((err) => {
            console.warn('Service worker registration failed', url, err);
            throw err;
        });
        register(__SERVICE_WORKER__).catch(() => {
            const inlineSource = __INLINE_SERVICE_WORKER__;
            if (!inlineSource) {
                return;
            }
            const blob = new Blob([inlineSource], { type: 'text/javascript' });
            register(URL.createObjectURL(blob)).catch((err) => {
                console.warn('Fallback service worker registration failed', err);
            });
        });
    }
})();
</script>
    """
    script = (
        script_template
        .replace("__MANIFEST__", manifest_href)
        .replace("__ICON32__", icon32_href)
        .replace("__ICON192__", icon192_href)
        .replace("__ICON512__", icon512_href)
        .replace("__SERVICE_WORKER__", service_worker_href)
        .replace("__INLINE_SERVICE_WORKER__", inline_service_worker)
    )
    st.markdown(script, unsafe_allow_html=True)

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
        "Missing required environment variables."
        f" Set the following in Railway: {', '.join(missing_required)}"
    )
    st.stop()

# Configure logging early for deployment diagnostics
logging.basicConfig(level=logging.INFO)
logging.info("Starting The Christian Project Streamlit server...")
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

# To set key locally: echo "OPENAI_API_KEY=yourkey" > .env
# For deployment: add OPENAI_API_KEY as an environment variable in the hosting platform.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("OpenAI API key not found. Please set it in your environment or a .env file.")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)
# TODO: Secure key handling for multi-user hosting (user tokens vs global key).

os.environ["TOKENIZERS_PARALLELISM"] = "false"

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
    st.warning(f"{message}\n\n**{verse}**")


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
    """
    Log question/answer pairs for pastoral review via the dashboard.

    Args:
        question: The sanitized user question
        assistant_payload: The assistant response containing answer and metadata
    """
    try:
        # Extract relevant data from assistant payload
        answer = assistant_payload.get("content", "")
        sources = assistant_payload.get("sources", [])

        # Determine topic cluster from sources (if available)
        topic_cluster = "General"  # Default to proper case "General"
        if sources and isinstance(sources, dict):
            # Try to extract topic from doctrine or contextual sources
            doctrine_sources = sources.get("doctrine", [])
            contextual_sources = sources.get("contextual", [])

            # Try doctrine sources first, then contextual
            source_list = doctrine_sources if doctrine_sources else contextual_sources

            if source_list and len(source_list) > 0:
                first_source = source_list[0]
                if isinstance(first_source, dict):
                    topic = first_source.get("topic", "General")
                    # Normalize to proper case
                    topic_cluster = topic.title() if topic else "General"

        # Calculate tone score (if available in payload)
        tone_score = 0.5  # default neutral
        if "tone_score" in assistant_payload:
            tone_score = assistant_payload["tone_score"]

        # Create review entry
        entry = {
            "response_id": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f"),
            "question": sanitize_text(question),
            "answer": sanitize_text(answer),
            "topic_cluster": topic_cluster,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tone_score": tone_score,
            "user_id": "anonymous"  # Future: integrate with auth system
        }

        # Ensure directory exists
        REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)

        # Append to JSONL file
        with REVIEW_QUEUE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")

        logging.info(f"Question logged for pastoral review: {entry['response_id']}")

    except Exception as e:
        logging.error(f"Error logging question for pastoral review: {e}")
        # Don't raise - logging failure shouldn't break chat functionality




def synthesize_with_gpt(question: str, context: str) -> Optional[str]:
    """
    Synthesize a response using GPT-4o-mini with improved prompting.

    Uses gpt-4o-mini for better accuracy and 66% cost savings vs gpt-3.5-turbo.
    Temperature: 0.3 for more consistent responses
    Max tokens: 800 for complete answers
    """
    # Improved system prompt
    system_prompt = """You are a theological assistant trained in WELS Lutheran doctrine and Scripture.

Your role:
- Provide clear, accurate answers grounded in biblical teaching
- Stay faithful to Scripture and WELS Lutheran theology
- Reference specific sources when making theological claims
- Use natural, conversational language

IMPORTANT: When using information from the provided sources, cite them naturally
(e.g., "According to WELS teaching..." or "As Scripture teaches...").
"""

    # Format the user prompt with better structure
    user_prompt = f"""Based on the following sources from Scripture and Lutheran theology, answer this question:

Question: {question}

Available Sources:
{context}

Instructions:
1. Answer clearly and directly
2. Reference the sources in your response when relevant
3. Stay faithful to what Scripture and the sources actually teach
4. Use natural, pastoral language

Provide a thoughtful, scripturally-grounded response:"""

    try:
        completion = client.chat.completions.create(
            model=os.getenv("OPENAI_COMPLETIONS_MODEL", "gpt-4o-mini"),
            temperature=0.3,  # More consistent than 0.4
            max_tokens=800,   # More complete responses than default
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
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
        page_icon=_page_icon(),
        layout="wide",
    )
    inject_pwa_metadata()
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
        "Unable to load retrieval utilities. Please verify the `scripts` package is present and importable."
    )
    st.caption(f"Debug detail: {exc}")
    st.stop()



st.set_page_config(
    page_title="The Christian Project",
    page_icon=_page_icon(),
    layout="wide",
    initial_sidebar_state="auto",  # Changed from "collapsed" to support multi-page navigation
    menu_items={
        'Get Help': None,
        'Report a bug': None,
        'About': None
    }
)
inject_pwa_metadata()

st.markdown("""
<style>
/* Mobile First CSS Reset */
* {
    box-sizing: border-box;
    max-width: 100%;
    overflow-wrap: break-word;
}

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
    --text-muted: rgba(46, 46, 46, 0.85);
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
    --divider: rgba(75, 46, 5, 0.20);
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
    --text-muted: rgba(207, 200, 184, 0.85);
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
        --text-muted: rgba(207, 200, 184, 0.85);
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
    /* Fluid font size: 16px at 375px viewport, 18px at 1440px */
    font-size: clamp(1rem, 0.9rem + 0.25vw, 1.125rem);
    /* Optimal line height for readability */
    line-height: 1.625;
    max-width: 100%;
}

/* Prevent iOS zoom on input focus */
body, input, textarea, button, select {
    font-size: 16px !important;
}

/* Touch targets for mobile */
button, .clickable, [role="button"] {
    min-height: 44px;
    min-width: 44px;
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
    width: 2.75rem;
    height: 2.75rem;
    border-radius: 14px;
    display: grid;
    place-items: center;
    background: var(--surface-floating);
    box-shadow: var(--shadow-soft);
    border: 1px solid var(--divider);
    overflow: hidden;
}

.sidebar-brand-icon img {
    width: 2.05rem;
    height: 2.05rem;
    object-fit: contain;
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
    cursor: pointer;
    transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease;
    position: relative;
    overflow: hidden;
}

.sidebar-panel button[data-testid="baseButton-primary"]:hover {
    background: var(--button-bg-hover);
    box-shadow: var(--shadow-hover);
    transform: translateY(-1px) scale(1.02);
}

.sidebar-panel button[data-testid="baseButton-primary"]:active {
    background: var(--button-bg);
    box-shadow: 0 2px 6px rgba(75, 46, 5, 0.15);
    transform: translateY(0) scale(0.98);
}

.sidebar-panel button[data-testid="baseButton-primary"]:focus-visible {
    outline: 2px solid var(--focus-outline);
    outline-offset: 2px;
    box-shadow: var(--shadow-soft), 0 0 0 4px rgba(75, 46, 5, 0.2);
}

.sidebar-panel button[data-testid="baseButton-primary"]:disabled {
    background: var(--surface-elevated);
    color: var(--text-muted);
    cursor: not-allowed;
    opacity: 0.6;
    box-shadow: none;
    transform: none;
}

.sidebar-panel button[data-testid="baseButton-secondary"] {
    background: var(--surface-floating);
    color: var(--text-primary);
    border: 1px solid var(--divider);
    padding: 0.6rem 0.85rem;
    justify-content: flex-start;
    gap: 0.5rem;
    cursor: pointer;
    transition: transform 0.2s ease, box-shadow 0.2s ease, background-color 0.2s ease, border-color 0.2s ease;
}

.sidebar-panel button[data-testid="baseButton-secondary"]:hover {
    box-shadow: var(--shadow-soft);
    transform: translateY(-1px);
    border-color: var(--accent);
    background: var(--surface-elevated);
}

.sidebar-panel button[data-testid="baseButton-secondary"]:active {
    transform: translateY(0) scale(0.98);
    box-shadow: none;
}

.sidebar-panel button[data-testid="baseButton-secondary"]:focus-visible {
    outline: 2px solid var(--focus-outline);
    outline-offset: 2px;
    border-color: var(--accent);
}

.sidebar-panel button[data-testid="baseButton-secondary"]:disabled {
    background: var(--surface-elevated);
    color: var(--text-muted);
    border-color: var(--divider);
    cursor: not-allowed;
    opacity: 0.5;
    transform: none;
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
    font-size: clamp(1.5rem, 5vw, 2rem);
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
    max-width: 88%;
    padding: 1rem 1.25rem;
    border-radius: 20px;
    box-shadow: 0 8px 18px rgba(0, 0, 0, 0.08);
    animation: messageFade 0.25s ease-out;
    backdrop-filter: blur(0.25px);
    margin-bottom: 0.5rem;
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

.stChatMessage .stMarkdown p {
    color: var(--text-primary) !important;
    font-size: clamp(0.95rem, 0.9rem + 0.25vw, 1.05rem);
    line-height: 1.7;
    margin-bottom: 0.75em;
    max-width: 65ch;
}

.stChatMessage .stMarkdown p:last-child {
    margin-bottom: 0;
}

.stChatMessage .stMarkdown li {
    color: var(--text-primary) !important;
    line-height: 1.6;
    margin-bottom: 0.5rem;
}

.stChatMessage .stMarkdown ul,
.stChatMessage .stMarkdown ol {
    margin: 0.75em 0;
    padding-left: 1.5em;
}

.stChatMessage .stMarkdown a {
    color: var(--accent);
    text-decoration: underline;
    text-decoration-thickness: 1px;
    text-underline-offset: 2px;
    transition: color 0.2s ease;
}

.stChatMessage .stMarkdown a:hover {
    color: var(--button-bg-hover);
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
    border-radius: 8px !important;
    border: 1px solid var(--input-border) !important;
    color: var(--text-primary) !important;
    padding: 0.75rem 1rem !important;
    font-size: 1rem !important;
    font-family: var(--font-ui) !important;
    transition: border-color 0.15s ease;
}

.chat-input-region textarea:focus-visible {
    border-color: var(--accent) !important;
    box-shadow: none !important;
    outline: none !important;
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

/* Mobile Responsiveness - iPhone SE (375px) and up */
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
        margin-left: 1rem;
        margin-right: 1rem;
        padding-left: 0.25rem;
        padding-right: 0.25rem;
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
        bottom: env(safe-area-inset-bottom, 0);
        width: 100%;
        margin: 0;
        border-radius: 24px 24px 0 0;
        z-index: 15;
        max-height: 45vh;
        overflow-y: auto;
        transition: bottom 0.2s ease-out;
        padding: 1rem 1rem 1.25rem !important;
        box-shadow: 0 -4px 20px rgba(0, 0, 0, 0.12);
    }

    /* Larger textarea on mobile for better touch */
    .app-shell.mobile-view .chat-input-region textarea {
        min-height: 52px !important;
        padding: 0.9rem 1rem !important;
        font-size: 16px !important;
        border-radius: 16px !important;
    }

    /* Larger send button on mobile */
    .app-shell.mobile-view .chat-input-region button[data-testid="baseButton-secondary"] {
        min-height: 52px !important;
        min-width: 52px !important;
        padding: 0 1.25rem !important;
    }

    /* Mobile message bubbles - more spacious and readable */
    .stChatMessage > div {
        max-width: 92% !important;
        word-wrap: break-word;
        padding: 1.1rem 1.35rem !important;
        margin-bottom: 0.75rem !important;
        border-radius: 22px !important;
    }

    .stChatMessage .stMarkdown p {
        font-size: 1rem !important;
        line-height: 1.75 !important;
    }

    /* More space between messages */
    .stChatMessage {
        margin-bottom: 0.5rem !important;
    }

    /* Adjust padding for mobile - increased horizontal space */
    main .block-container {
        padding: 1.25rem 1rem 7rem;
    }

    /* Ensure sidebar is accessible on mobile */
    section[data-testid="stSidebar"] {
        max-width: 80vw;
    }
}

/* Tablet breakpoint (iPad 768px) */
@media (min-width: 769px) and (max-width: 1024px) {
    main .block-container {
        padding: 1.5rem 2rem 8rem;
    }
}

/* Desktop breakpoint */
@media (min-width: 1025px) {
    main .block-container {
        padding: 2rem 3rem 8rem;
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

/* Smooth animations and micro-interactions */
@keyframes messageFade {
    from {
        opacity: 0;
        transform: translateY(12px) scale(0.98);
    }
    to {
        opacity: 1;
        transform: translateY(0) scale(1);
    }
}

@keyframes slideInFromLeft {
    from {
        transform: translateX(-100%);
        opacity: 0;
    }
    to {
        transform: translateX(0);
        opacity: 1;
    }
}

@keyframes spin {
    from {
        transform: rotate(0deg);
    }
    to {
        transform: rotate(360deg);
    }
}

@keyframes shimmer {
    0% {
        background-position: -468px 0;
    }
    100% {
        background-position: 468px 0;
    }
}

/* Sidebar slide animation */
.sidebar-panel {
    animation: slideInFromLeft 0.3s cubic-bezier(0.16, 1, 0.3, 1);
}

/* Smooth transitions for all interactive elements */
button, .clickable, a, [role="button"] {
    transition:
        background-color 200ms cubic-bezier(0.4, 0, 0.2, 1),
        transform 150ms cubic-bezier(0.4, 0, 0.2, 1),
        box-shadow 200ms cubic-bezier(0.4, 0, 0.2, 1),
        color 200ms cubic-bezier(0.4, 0, 0.2, 1),
        border-color 200ms cubic-bezier(0.4, 0, 0.2, 1);
}

/* Respect user motion preferences */
@media (prefers-reduced-motion: reduce) {
    *,
    *::before,
    *::after {
        animation-duration: 0.01ms !important;
        animation-iteration-count: 1 !important;
        transition-duration: 0.01ms !important;
        scroll-behavior: auto !important;
    }
}

/* Screen reader only content - accessible but visually hidden */
.sr-only {
    position: absolute;
    width: 1px;
    height: 1px;
    padding: 0;
    margin: -1px;
    overflow: hidden;
    clip: rect(0,0,0,0);
    white-space: nowrap;
    border-width: 0;
}

/* Skip to main content link - appears on focus for keyboard users */
.skip-link {
    position: absolute;
    top: -40px;
    left: 0;
    background: var(--accent);
    color: var(--accent-contrast);
    padding: 0.5rem 1rem;
    z-index: 100;
    text-decoration: none;
    border-radius: 0 0 8px 0;
    font-weight: 600;
    transition: top 0.2s ease;
}

.skip-link:focus {
    top: 0;
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
        if (typeof window.__tcp_apply_theme === "function") {
            window.__tcp_apply_theme();
        }
        return;
    }
    window.__tcp_ui_enhancer_initialized = true;

    // Theme management function
    window.__tcp_apply_theme = function() {
        // First, check for theme state from hidden div (most reliable)
        const themeDiv = doc.getElementById('theme-state');
        if (themeDiv) {
            const theme = themeDiv.getAttribute('data-theme');
            if (theme === 'dark') {
                body.setAttribute('data-theme', 'dark');
                return;
            } else if (theme === 'light') {
                body.removeAttribute('data-theme');
                return;
            }
        }

        // Fallback: Check if user has selected a theme via radio button
        const radioButtons = doc.querySelectorAll('input[type="radio"]');
        let userTheme = null;
        radioButtons.forEach((radio) => {
            if (radio.checked) {
                const label = radio.closest('label');
                if (label && label.textContent) {
                    const text = label.textContent.trim();
                    if (text.includes('Dark')) {
                        userTheme = 'dark';
                    } else if (text.includes('Light')) {
                        userTheme = 'light';
                    }
                }
            }
        });

        if (userTheme === 'dark') {
            body.setAttribute('data-theme', 'dark');
        } else if (userTheme === 'light') {
            body.removeAttribute('data-theme');
        } else {
            // Fall back to system preference if no explicit selection
            const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
            if (mediaQuery.matches) {
                body.setAttribute('data-theme', 'dark');
            } else {
                body.removeAttribute('data-theme');
            }
        }
    };

    // Apply theme on load and when radio buttons change
    window.__tcp_apply_theme();
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    if (mediaQuery.addEventListener) {
        mediaQuery.addEventListener('change', window.__tcp_apply_theme);
    } else if (mediaQuery.addListener) {
        mediaQuery.addListener(window.__tcp_apply_theme);
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
            btn.setAttribute('aria-expanded', 'false');
            btn.setAttribute('aria-controls', 'sidebar-panel');
            btn.setAttribute('title', 'Open navigation menu');
            btn.setAttribute('type', 'button');

            // Add keyboard navigation
            btn.addEventListener('keydown', (e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    btn.click();
                }
            });
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

        // Add ARIA labels to primary buttons like "New Chat"
        const primaryButtons = doc.querySelectorAll('[data-testid="baseButton-primary"]');
        primaryButtons.forEach((btn) => {
            if (!btn.getAttribute('aria-label') && btn.textContent.includes('New Chat')) {
                btn.setAttribute('aria-label', 'Start new conversation');
                btn.setAttribute('title', 'Start new conversation');
            }
        });

        // Make chat messages keyboard focusable
        const messages = doc.querySelectorAll('.stChatMessage');
        messages.forEach((msg, idx) => {
            if (!msg.getAttribute('tabindex')) {
                msg.setAttribute('tabindex', '0');
                msg.setAttribute('role', 'article');
                msg.setAttribute('aria-label', `Message ${idx + 1}`);
            }
        });

        // Add skip to main content link for keyboard users
        if (!doc.getElementById('skip-to-main')) {
            const skipLink = doc.createElement('a');
            skipLink.id = 'skip-to-main';
            skipLink.href = '#main-content';
            skipLink.textContent = 'Skip to main content';
            skipLink.className = 'skip-link';
            skipLink.addEventListener('click', (e) => {
                e.preventDefault();
                const main = doc.querySelector('main') || doc.querySelector('[role="main"]');
                if (main) {
                    main.setAttribute('tabindex', '-1');
                    main.focus();
                }
            });
            body.insertBefore(skipLink, body.firstChild);
        }

        // Mark main content area
        const mainContent = doc.querySelector('main');
        if (mainContent && !mainContent.id) {
            mainContent.id = 'main-content';
            mainContent.setAttribute('role', 'main');
        }
    };

    const observer = new MutationObserver(() => {
        enhanceButtons();
        window.__tcp_apply_theme();
    });
    observer.observe(doc, { childList: true, subtree: true });
    enhanceButtons();
    window.__tcp_refresh_buttons = enhanceButtons;

    // Mobile keyboard handling for iOS and Android
    if ('visualViewport' in window) {
        let keyboardVisible = false;
        let dismissBar = null;

        const blurActiveInput = () => {
            const activeEl = doc.activeElement;
            if (activeEl && (activeEl.tagName === 'INPUT' || activeEl.tagName === 'TEXTAREA')) {
                activeEl.blur();
            }
        };

        const createDismissBar = () => {
            if (dismissBar) return dismissBar;

            // Create a "Done" bar that appears above the keyboard
            dismissBar = doc.createElement('div');
            dismissBar.id = 'tcp-keyboard-dismiss-bar';
            dismissBar.innerHTML = `
                <button type="button" id="tcp-done-btn">Done</button>
            `;
            dismissBar.style.cssText = `
                position: fixed;
                left: 0;
                right: 0;
                height: 44px;
                background: var(--surface-header, #f1e9dc);
                border-top: 1px solid var(--divider, rgba(75, 46, 5, 0.2));
                display: none;
                align-items: center;
                justify-content: flex-end;
                padding: 0 1rem;
                z-index: 16;
                box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.08);
            `;

            const doneBtn = dismissBar.querySelector('#tcp-done-btn');
            doneBtn.style.cssText = `
                background: transparent;
                border: none;
                color: var(--accent, #4b2e05);
                font-weight: 600;
                font-size: 1rem;
                padding: 0.5rem 1rem;
                cursor: pointer;
                font-family: var(--font-ui, sans-serif);
            `;
            doneBtn.addEventListener('click', blurActiveInput);

            doc.body.appendChild(dismissBar);
            return dismissBar;
        };

        const handleKeyboard = () => {
            const chatInput = doc.querySelector('.chat-input-region [data-testid="stChatInput"]');
            const chatScroll = doc.querySelector('.chat-scroll');
            const mainContainer = doc.querySelector('main .block-container');
            const keyboardHeight = window.innerHeight - window.visualViewport.height;
            const wasKeyboardVisible = keyboardVisible;
            keyboardVisible = keyboardHeight > 100; // Threshold to avoid false positives

            if (chatInput) {
                if (keyboardVisible) {
                    // Keyboard is visible - adjust input position and scroll
                    const inputBottom = keyboardHeight;
                    chatInput.style.bottom = `${inputBottom}px`;

                    // Show dismiss bar just above the input
                    const bar = createDismissBar();
                    bar.style.display = 'flex';
                    bar.style.bottom = `${inputBottom + chatInput.offsetHeight}px`;

                    // Add extra padding to main content so messages aren't hidden
                    if (mainContainer) {
                        mainContainer.style.paddingBottom = `${keyboardHeight + 140}px`;
                    }

                    // Auto-scroll to show latest message
                    if (chatScroll && !wasKeyboardVisible) {
                        setTimeout(() => {
                            chatScroll.scrollTop = chatScroll.scrollHeight;
                        }, 100);
                    }
                } else {
                    // Keyboard is hidden - reset everything
                    chatInput.style.bottom = 'env(safe-area-inset-bottom, 0)';

                    // Hide dismiss bar
                    if (dismissBar) {
                        dismissBar.style.display = 'none';
                    }

                    if (mainContainer) {
                        mainContainer.style.paddingBottom = '';
                    }

                }
            }
        };

        window.visualViewport.addEventListener('resize', handleKeyboard);
        window.visualViewport.addEventListener('scroll', handleKeyboard);

        // Also handle focus events for additional reliability
        doc.addEventListener('focusin', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                setTimeout(handleKeyboard, 300);
            }
        });

        doc.addEventListener('focusout', (e) => {
            if (e.target.tagName === 'INPUT' || e.target.tagName === 'TEXTAREA') {
                setTimeout(handleKeyboard, 100);
            }
        });

        // Initial check
        handleKeyboard();
    }
})();
</script>
""", unsafe_allow_html=True)

st.markdown("""
<style>
:root {
    --surface-card: #f6f0dc;
    --surface-muted: #efe4d0;
    --surface-sidebar: #f1e9dc;
    --accent: #4b2e05;
    --accent-hover: #6d4210;
    --accent-soft: rgba(75, 46, 5, 0.2);
    --inverse-text: #fffaf0;
    --shadow-light: 0 3px 12px rgba(0, 0, 0, 0.08);
}

body[data-theme="dark"] {
    --surface-card: #25201b;
    --surface-muted: #1f1b17;
    --surface-sidebar: #1f1b17;
    --accent: #d8b079;
    --accent-hover: #e2c48f;
    --accent-soft: rgba(216, 176, 121, 0.24);
    --inverse-text: #1f1b17;
    --shadow-light: 0 4px 16px rgba(0, 0, 0, 0.45);
}

@media (prefers-color-scheme: dark) {
    body:not([data-theme]) {
        --surface-card: #25201b;
        --surface-muted: #1f1b17;
        --surface-sidebar: #1f1b17;
        --accent: #d8b079;
        --accent-hover: #e2c48f;
        --accent-soft: rgba(216, 176, 121, 0.24);
        --inverse-text: #1f1b17;
        --shadow-light: 0 4px 16px rgba(0, 0, 0, 0.45);
    }
}

body, .stApp {
    background: var(--background);
    color: var(--text-primary);
    font-family: "Spectral", "Georgia", "Times New Roman", serif;
}

section[data-testid="stSidebar"] {
    background: var(--surface-sidebar);
    border-right: 1px solid var(--divider);
}

section[data-testid="stSidebar"] > div {
    padding: 1.75rem 1.5rem 3rem;
}

section[data-testid="stSidebar"] button[data-testid="baseButton-primary"] {
    background: var(--accent) !important;
    color: var(--inverse-text) !important;
    border-radius: 14px !important;
    border: none !important;
    font-weight: 600 !important;
    box-shadow: var(--shadow-soft);
}

section[data-testid="stSidebar"] button[data-testid="baseButton-primary"]:hover {
    background: var(--accent-hover) !important;
}

section[data-testid="stSidebar"] button[data-testid="baseButton-secondary"] {
    background: var(--surface-card) !important;
    color: var(--text-primary) !important;
    border: 1px solid var(--divider) !important;
    border-radius: 12px !important;
    font-family: var(--font-ui) !important;
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

.sidebar-brand-kicker {
    font-size: 0.78rem;
    letter-spacing: 0.22em;
    text-transform: uppercase;
    color: var(--text-muted);
    font-family: var(--font-ui);
}

.sidebar-brand-name {
    font-size: 1.18rem;
    font-weight: 600;
}

.sidebar-brand-subtitle {
    font-size: 0.92rem;
    color: var(--text-secondary);
    font-family: var(--font-ui);
}

.chat-wrapper {
    background: var(--surface-card);
    border-radius: 28px;
    padding: 1.75rem 1.85rem 2.2rem;
    box-shadow: var(--shadow-soft);
    border: 1px solid var(--divider);
    margin-bottom: 1.75rem;
}

.chat-header {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    margin-bottom: 1.4rem;
    align-items: center;
    text-align: center;
}

/* Hide duplicate headers that appear during Streamlit reruns */
.chat-header ~ .chat-header,
.chat-wrapper ~ .chat-wrapper .chat-header {
    display: none !important;
}

.chat-header-identity {
    display: flex;
    align-items: center;
    gap: 1rem;
}

.chat-header-logo {
    width: 3rem;
    height: 3rem;
    border-radius: 16px;
    display: grid;
    place-items: center;
    background: var(--surface-floating);
    box-shadow: var(--shadow-soft);
    border: 1px solid var(--divider);
    overflow: hidden;
}

.chat-header-logo img {
    width: 2.4rem;
    height: 2.4rem;
    object-fit: contain;
}

.chat-title-group {
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
    align-items: center;
    text-align: center;
}

.chat-title-group h1 {
    margin: 0;
    font-size: 1.65rem;
    font-weight: 600;
    color: var(--text-primary);
}

.chat-title-group p {
    margin: 0;
    color: var(--text-secondary);
    font-size: 0.95rem;
    font-family: var(--font-ui);
}

body[data-theme="dark"] .chat-title-group h1 {
    color: #fff7e3;
}

body[data-theme="dark"] .chat-title-group p {
    color: #e8dcc7;
}

.preview-pill {
    background: var(--surface-muted);
    color: var(--text-secondary);
    border-radius: 999px;
    padding: 0.35rem 0.9rem;
    font-size: 0.75rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    font-family: var(--font-ui);
}

.trust-panel {
    display: none;
}

.chat-scroll {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    max-height: min(64vh, 640px);
    overflow-y: auto;
}

.stChatMessage {
    background: transparent !important;
    padding: 0 !important;
}

.stChatMessage[data-testid="stChatMessage-Assistant"] > div {
    background: rgba(255, 255, 255, 0.85);
    border-radius: 18px;
    padding: 0.95rem 1.2rem;
    border: 1px solid var(--divider);
    box-shadow: var(--shadow-light);
    max-width: 90%;
}

.stChatMessage[data-testid="stChatMessage-User"] > div {
    background: rgba(75, 46, 5, 0.14);
    border-radius: 18px;
    padding: 0.9rem 1.15rem;
    border: 1px solid rgba(75, 46, 5, 0.22);
    box-shadow: var(--shadow-light);
    max-width: 90%;
    margin-left: auto;
}

body[data-theme="dark"] .stChatMessage[data-testid="stChatMessage-Assistant"] > div {
    background: rgba(40, 33, 27, 0.9);
}

body[data-theme="dark"] .stChatMessage[data-testid="stChatMessage-User"] > div {
    background: rgba(216, 176, 121, 0.12);
    border-color: rgba(216, 176, 121, 0.22);
}

.stChatInput {
    background: var(--surface-card);
    border-radius: 22px;
    box-shadow: var(--shadow-soft);
    padding: 1rem 1.25rem 1.35rem;
    border: 1px solid var(--divider);
}

.stChatInput textarea {
    background: var(--input-bg) !important;
    border: 1px solid var(--input-border) !important;
    border-radius: 8px !important;
    padding: 0.75rem 1rem !important;
    color: var(--text-primary) !important;
    font-family: var(--font-ui) !important;
}

.stChatInput textarea:focus-visible {
    border-color: var(--accent) !important;
    box-shadow: none !important;
    outline: none !important;
}

.stChatInput button[data-testid="baseButton-secondary"] {
    background: var(--accent) !important;
    color: var(--inverse-text) !important;
    border-radius: 999px !important;
    border: none !important;
    padding: 0 1.6rem !important;
    font-weight: 600 !important;
    font-family: var(--font-ui) !important;
    box-shadow: var(--shadow-light);
}

.stChatInput button[data-testid="baseButton-secondary"]:hover,
.stChatInput button[data-testid="baseButton-secondary"]:focus-visible {
    background: var(--accent-hover) !important;
}

.stChatInput button[data-testid="baseButton-secondary"] svg {
    display: none;
}

.doctrinal-footer {
    margin-top: 1.4rem;
    font-size: 0.82rem;
    font-style: italic;
    color: var(--text-muted);
    text-align: center;
    font-family: var(--font-ui);
}

/* Hide duplicate footers and trust panels during Streamlit reruns */
.doctrinal-footer ~ .doctrinal-footer,
.trust-panel ~ .trust-panel {
    display: none !important;
}

@media (max-width: 900px) {
    main .block-container {
        padding: 1.2rem 1rem 6.5rem;
    }
    .chat-wrapper {
        border-radius: 22px;
        padding: 1.35rem 1.2rem 2rem;
    }
    .chat-header {
        align-items: center;
        text-align: center;
    }
    .chat-header-identity {
        flex-direction: column;
        gap: 0.6rem;
    }
    .chat-title-group {
        align-items: center;
        text-align: center;
    }
    .stChatInput {
        position: fixed;
        left: 0.75rem;
        right: 0.75rem;
        bottom: 1rem;
        margin: 0;
        z-index: 50;
    }
}
</style>
""", unsafe_allow_html=True)



RETRIEVAL_UNAVAILABLE_MSG = (
    "The retrieval system is temporarily unavailable. Please check your setup or try again later."
)

def _initialize_ui_state() -> None:
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "conversation_archive" not in st.session_state:
        st.session_state.conversation_archive = {}
    if "show_about_modal" not in st.session_state:
        st.session_state.show_about_modal = False


def reset_conversation() -> None:
    st.session_state.chat_history = []
    st.session_state.last_question = None
    st.session_state.last_submission_time = 0.0
    st.session_state.last_activity = time.time()
    st.session_state.pop("user_input", None)


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
                st.rerun()
    else:
        st.info(
            "This assistant gives biblical answers according to confessional Lutheran teaching.\n\n"
            "- For personal spiritual care, please speak with your pastor.\n"
            "- Your questions may be reviewed by a pastor to improve clarity and faithfulness."
        )
        st.session_state.show_about_modal = False


def render_sidebar() -> None:
    with st.sidebar:
        st.markdown(
            """
            <div class="sidebar-brand">
                <div class="sidebar-brand-text">
                    <span class="sidebar-brand-name">✝ The Christian Project</span>
                    <span class="sidebar-brand-subtitle">Seeking wisdom through Scripture</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("New Chat", key="sidebar_new_chat", type="primary", use_container_width=True):
            reset_conversation()
            st.toast("Conversation cleared. Ready for a new question.")
            st.rerun()

        st.caption("Conversation history coming soon.")

        st.markdown("<div class='sidebar-section-title'>Guidance</div>", unsafe_allow_html=True)
        with st.expander("ℹ About This Tool", expanded=False):
            st.markdown(
                """
                This tool was created to provide people with Biblically accurate answers pertaining to scripture.
                This doesn't replace a pastor or the bible in anyway, please do not take anything as the final word.
                """
            )

        st.markdown("<div class='sidebar-section-title'>◐ Appearance</div>", unsafe_allow_html=True)

        # Initialize theme in session state
        if 'theme' not in st.session_state:
            st.session_state.theme = 'light'

        theme = st.radio(
            "Theme",
            options=["Light (Parchment)", "Dark"],
            key="theme_selection",
            index=0 if st.session_state.theme == 'light' else 1,
            label_visibility="collapsed"
        )

        # Update theme in session state
        new_theme = 'light' if 'Light' in theme else 'dark'
        if new_theme != st.session_state.theme:
            st.session_state.theme = new_theme
            st.rerun()

        # Hidden div to communicate theme to JavaScript
        st.markdown(
            f'<div id="theme-state" data-theme="{st.session_state.theme}" style="display:none;"></div>',
            unsafe_allow_html=True
        )


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


def render_main_header() -> None:
    st.markdown(
        """
        <div class="chat-header">
            <div class="chat-header-identity">
                <div class="chat-title-group">
                    <h1>✝ The Christian Project</h1>
                    <p>Faithful answers for curious hearts</p>
                </div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_doctrinal_footer() -> None:
    st.markdown(
        '<div class="doctrinal-footer">This assistant provides biblically faithful information but is not a substitute for pastoral care. Please speak with your pastor for personal guidance.</div>',
        unsafe_allow_html=True,
    )


def display_chat_history() -> None:
    st.markdown(
        '<div id="chat-scroll-region-main" class="chat-scroll" role="log" aria-live="polite" aria-label="Conversation transcript">',
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
                total_sources = len(doctrine_sources) + len(contextual_sources)
                with st.expander(f"📚 View {total_sources} source(s)", expanded=False):
                    source_num = 1

                    if doctrine_sources:
                        st.markdown("### Doctrinal Sources")
                        for item in doctrine_sources:
                            score = item.get('score', 0.0)
                            relevance = "🟢 High" if score > 0.85 else "🟡 Medium" if score > 0.70 else "🟠 Moderate"

                            # Extract title and content from available fields
                            doc_title = item.get('title') or 'WELS Doctrine'
                            source_type = item.get('type', 'unknown')
                            category = item.get('category')
                            source_name = item.get('source')

                            # Build a better display title
                            display_title = doc_title
                            if category:
                                display_title = f"{category} - {doc_title}" if len(doc_title) < 50 else category
                            elif source_name:
                                display_title = f"{source_name} - {doc_title}" if len(doc_title) < 50 else source_name

                            st.markdown(f"**Source {source_num}: {display_title}**")

                            # Extract content from appropriate field based on data structure
                            # Priority: scripture (for devotions), title (for doctrines), answer (for Q&A), content
                            content_text = None
                            if item.get('scripture'):
                                content_text = item['scripture']
                                if source_type == 'devotion':
                                    st.caption(f"Type: Devotion")
                            elif item.get('question'):
                                # Q&A format
                                st.caption(f"Question: {item['question'][:100]}...")
                                content_text = item.get('answer', '')
                            elif item.get('title') and source_type == 'doctrine':
                                # For doctrine entries, the title IS the doctrinal statement
                                content_text = item['title']
                            elif item.get('content'):
                                content_text = item['content']

                            if content_text:
                                preview = content_text[:300] + "..." if len(content_text) > 300 else content_text
                                st.markdown(f"> {preview}")
                            else:
                                st.markdown(f"> _Content preview unavailable_")

                            st.caption(f"{relevance} (Score: {score:.2f})")
                            if source_num < total_sources:
                                st.markdown("---")
                            source_num += 1

                    if contextual_sources:
                        if doctrine_sources:
                            st.markdown("")
                        st.markdown("### Contextual Sources")
                        for item in contextual_sources:
                            score = item.get('score', 0.0)
                            relevance = "🟢 High" if score > 0.85 else "🟡 Medium" if score > 0.70 else "🟠 Moderate"

                            doc_title = item.get('title', 'WELS Resource')
                            category = item.get('category')
                            source_name = item.get('source')

                            # Build display title
                            display_title = doc_title
                            if category:
                                display_title = f"{category}" if len(doc_title) > 60 else f"{category} - {doc_title}"
                            elif source_name:
                                display_title = f"{source_name}" if len(doc_title) > 60 else f"{source_name} - {doc_title}"

                            st.markdown(f"**Source {source_num}: {display_title}**")

                            # Show URL if available
                            url = item.get('url')
                            if url:
                                st.caption(f"Link: [{url}]({url})")

                            # Extract content from appropriate field
                            content_text = None
                            if item.get('scripture'):
                                content_text = item['scripture']
                            elif item.get('title'):
                                content_text = item['title']
                            elif item.get('content'):
                                content_text = item['content']

                            if content_text:
                                preview = content_text[:300] + "..." if len(content_text) > 300 else content_text
                                st.markdown(f"> {preview}")
                            else:
                                st.markdown(f"> _Content preview unavailable_")

                            st.caption(f"{relevance} (Score: {score:.2f})")
                            if source_num < total_sources:
                                st.markdown("---")
                            source_num += 1
            if tone_score is not None and st.session_state.get("developer_mode"):
                st.caption(f"Tonal alignment score: {tone_score}")
            if warnings:
                for warning in warnings:
                    st.caption(f"Note: {warning}")

            feedback_container = st.container()
            with feedback_container:
                st.markdown(
                    "<div class='feedback-wrapper'><p>How helpful was this answer?</p></div>",
                    unsafe_allow_html=True,
                )
            col1, col2 = st.columns([1, 1], gap="small")
            with col1:
                if st.button(
                    "Helpful",
                    key=f"feedback_pos_{idx}",
                    use_container_width=True,
                ):
                    record_feedback(
                        "positive",
                        message.get("question", ""),
                        message["content"],
                    )
                    st.toast("Thank you for your feedback!")
            with col2:
                if st.button(
                    "Needs Review",
                    key=f"feedback_neg_{idx}",
                    use_container_width=True,
                ):
                    record_feedback(
                        "negative",
                        message.get("question", ""),
                        message["content"],
                    )
                    st.toast("Feedback recorded for review.")

    st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(
        """
        <script>
        (function() {
            const doc = window.parent?.document || document;
            const region = doc.getElementById("chat-scroll-region-main");
            if (region) {
                region.scrollTop = region.scrollHeight;
            }
        })();
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
    # Simple spinner - no verbose status messages
    with st.spinner(""):
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
    """Process user input with validation, rate limiting, and PII redaction."""
    user_input = user_input_raw.strip()

    # Input validation: Check for empty input
    if not user_input:
        return

    # Input validation: Check maximum length (2000 characters)
    MAX_CHARS = 2000
    char_count = len(user_input)

    if char_count > MAX_CHARS:
        st.error(
            f"⚠️ Your question is too long ({char_count}/{MAX_CHARS} characters).\n\n"
            "Please shorten your question to under 2000 characters for better responses."
        )
        with st.expander("💡 Tips for shorter questions"):
            st.markdown("""
            - Focus on one main question at a time
            - Remove unnecessary details
            - Be specific and concise
            - You can always ask follow-up questions
            """)
        st.stop()

    # Input validation: Check minimum length
    MIN_CHARS = 3
    if char_count < MIN_CHARS:
        st.warning(
            f"📝 Your question is very brief ({char_count} characters).\n\n"
            "Please provide more detail so we can give you a helpful answer."
        )
        with st.expander("💡 Tips for better questions"):
            st.markdown("""
            - Ask about specific theological topics
            - Include context if helpful
            - Be clear about what you want to understand

            **Examples:**
            - "What does the Bible say about prayer?"
            - "How do I explain the Trinity to my child?"
            - "What is the Lutheran view on Holy Communion?"
            """)
        st.stop()

    # Initialize rate limiting session state
    if "request_history" not in st.session_state:
        st.session_state.request_history = []

    # Rate limiting: Allow 10 requests per minute
    current_time = time.time()
    minute_ago = current_time - 60

    # Clean up old requests
    st.session_state.request_history = [
        t for t in st.session_state.request_history if t > minute_ago
    ]

    # Check rate limit
    if len(st.session_state.request_history) >= 10:
        st.error("You've reached the question limit. Please wait a moment before asking another question.")
        st.stop()

    # Prevent duplicate submissions
    if "last_question" not in st.session_state:
        st.session_state.last_question = None
    if user_input == st.session_state.last_question:
        st.stop()

    # Prevent rapid successive submissions (1 second cooldown)
    if "last_submission_time" not in st.session_state:
        st.session_state.last_submission_time = 0.0

    if current_time - st.session_state.last_submission_time < 1:
        st.warning("Please wait a moment before submitting another question.")
        st.stop()

    # Apply PII redaction to user input before processing
    try:
        sanitized_input = sanitize_text(user_input)
        # Log if PII was detected (for monitoring)
        if sanitized_input != user_input:
            logging.info("PII detected and redacted from user input")
    except Exception as exc:
        logging.warning("PII redaction failed, using original input: %s", exc)
        sanitized_input = user_input

    st.session_state.last_submission_time = current_time
    st.session_state.last_question = user_input
    st.session_state.request_history.append(current_time)

    try:
        assistant_message = handle_question(sanitized_input)
    except Exception as exc:
        st.session_state.last_question = None
        logging.exception("Error while generating response: %s", exc)
        show_grace_message()
        return

    # Store sanitized version in chat history to protect user privacy
    st.session_state.chat_history.append(
        {"role": "user", "content": sanitized_input, "question": sanitized_input}
    )
    st.session_state.chat_history.append(assistant_message)
    push_for_pastoral_review(sanitized_input, assistant_message)
    # Toast removed to prevent double-render banner issue during question processing


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
        st.toast("Conversation cleared")
    st.session_state.last_activity = time.time()

    render_sidebar()

    with st.container():
        st.markdown('<div class="chat-wrapper">', unsafe_allow_html=True)
        render_main_header()
        render_trust_panel()
        display_chat_history()
        render_doctrinal_footer()
        st.markdown("</div>", unsafe_allow_html=True)

    user_input = st.chat_input(
        "Ask a theological question...", key="user_input"
    )

    if user_input:
        process_input(user_input)
        st.session_state.pop("user_input", None)
        st.rerun()

    render_about_modal()


try:
    run_chat_interface()
    logging.info(
        "System update complete. Unified responsive layout restored for MVP showcase with refreshed styling and stable sidebar/header behavior."
    )
except Exception as exc:
    logging.exception("Unhandled error in interface: %s", exc)
    show_grace_message()
    st.stop()
