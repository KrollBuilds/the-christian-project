"""Streamlit chat interface for The Christian Project."""

from __future__ import annotations

# TODO: move logs to encrypted storage (e.g., Supabase or Firestore)
# TODO: implement admin metrics dashboard for usage and cost

# Developer toggle: st.session_state["developer_mode"] = True to show tonal metrics
# TODO: Future Phase — Convert this Streamlit prototype into a FastAPI backend with REST endpoints for /query and /review.

import base64
import copy
import json
import logging
import os
import random
import re
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

try:
    from app.utils.auto_train import maybe_auto_train
except Exception:
    def maybe_auto_train(*a, **kw): return False  # type: ignore

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

def _get_active_api_key() -> Optional[str]:
    """Return the configured server-side OpenAI key.

    A public relaunch should not ask church users to paste API keys into the UI.
    Streamlit secrets are checked first so hosted deployments can keep secrets
    outside the repository.
    """
    return _first_non_empty(
        _get_streamlit_secret("OPENAI_API_KEY"),
        _get_streamlit_secret("openai", "api_key"),
        os.getenv("OPENAI_API_KEY"),
    )


def _review_logging_enabled() -> bool:
    return os.getenv("ENABLE_REVIEW_LOGGING", "false").strip().lower() in {
        "1",
        "true",
        "yes",
    }

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
    system_prompt = """You are a biblical question assistant grounded in vetted Lutheran teaching.

Your role:
- Answer clearly, calmly, and briefly.
- Stay within the provided vetted context.
- Do not invent doctrine or speculate beyond the context.
- Do not include source lists, retrieval details, confidence scores, or system language.
- Recommend pastoral care when the question is personal, urgent, or sensitive.
"""

    user_prompt = f"""Answer the user's biblical question using only the vetted context below.

Question: {question}

Vetted context:
{context}

Instructions:
1. Give the direct answer first.
2. Use natural language for a normal church member.
3. Keep the answer focused and useful.
4. If the context does not support a claim, do not make that claim.

Answer:"""

    active_key = _get_active_api_key()
    if not active_key:
        st.error("OpenAI is not configured. Set OPENAI_API_KEY in the deployment environment.")
        return None
    synthesis_client = OpenAI(api_key=active_key)
    try:
        completion = synthesis_client.chat.completions.create(
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
        "The answer system is temporarily unavailable. Please try again later."
    )
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

_HOME_CSS_PATH = Path(__file__).parent / "ui" / "home.css"
_HOME_JS_PATH = Path(__file__).parent / "ui" / "home.js"


def _inject_assets() -> None:
    """Inject app CSS and JS from external files (single source of truth)."""
    try:
        css = _HOME_CSS_PATH.read_text(encoding="utf-8")
        st.markdown(f"<style>{css}</style>", unsafe_allow_html=True)
    except FileNotFoundError:
        logging.warning("Home CSS asset missing: %s", _HOME_CSS_PATH)
    try:
        js = _HOME_JS_PATH.read_text(encoding="utf-8")
        st.markdown(f"<script>{js}</script>", unsafe_allow_html=True)
    except FileNotFoundError:
        logging.warning("Home JS asset missing: %s", _HOME_JS_PATH)


_inject_assets()



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
                <div class="sidebar-cross" aria-hidden="true">✝</div>
                <div class="sidebar-brand-text">
                    <span class="sidebar-brand-name">The Christian Project</span>
                    <span class="sidebar-brand-subtitle">Seeking wisdom through Scripture</span>
                </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        if st.button("New Chat", key="sidebar_new_chat", type="primary", use_container_width=True):
            reset_conversation()
            st.rerun()

        st.markdown("<div class='sidebar-section-title'>Appearance</div>", unsafe_allow_html=True)

        # Initialize theme in session state
        if 'theme' not in st.session_state:
            st.session_state.theme = 'dark'

        theme = st.radio(
            "Theme",
            options=["Light", "Dark"],
            key="theme_selection",
            index=1 if st.session_state.theme == 'dark' else 0,
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
            Ask a biblical question. Avoid sharing private personal details.
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_main_header() -> None:
    st.markdown(
        """
        <div class="chat-header">
            <div class="chat-header-identity">
                <div class="chat-header-cross" aria-hidden="true">✝</div>
                <div class="chat-title-group">
                    <h1>The Christian Project</h1>
                    <p>Ask a biblical question</p>
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
    for message in st.session_state.get("chat_history", []):
        role = message["role"]
        with st.chat_message(role):
            st.markdown(message["content"])

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

    best_source = (doctrine_sources or contextual_sources)[0]
    question_text = str(best_source.get("question") or "").strip()
    content_text = str(
        best_source.get("answer")
        or best_source.get("content")
        or best_source.get("body")
        or best_source.get("title")
        or ""
    )
    content_text = re.sub(r"<[^>]+>", " ", content_text)
    content_text = re.sub(r"\s+", " ", content_text).strip()

    if not content_text:
        message = "I found related material, but I cannot turn it into a reliable answer while the answer service is unavailable."
        return append_pastoral_guidance(message)

    content_text = textwrap.shorten(content_text, width=900, placeholder="...")
    if question_text:
        message = f"The closest vetted teaching I found asks, \"{question_text}\" It says: {content_text}"
    else:
        message = content_text
    return append_pastoral_guidance(message)


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
            answer = append_pastoral_guidance(
                "I do not have enough vetted material in this project to answer that faithfully."
            )
            warnings.append("No vetted context found.")
        else:
            answer = synthesize_with_gpt(question, "\n\n".join(context_sections))

        if answer is None:
            warnings.append("Synthesis service unavailable.")
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
    if _review_logging_enabled():
        push_for_pastoral_review(sanitized_input, assistant_message)



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

    if not _get_active_api_key():
        st.error("OpenAI is not configured. Set OPENAI_API_KEY before relaunching this app.")
    else:
        user_input = st.chat_input(
            "Ask a biblical question...", key="user_input"
        )
        if user_input:
            process_input(user_input)
            st.session_state.pop("user_input", None)
            st.rerun()



try:
    run_chat_interface()
    logging.info(
        "System update complete. Unified responsive layout restored for MVP showcase with refreshed styling and stable sidebar/header behavior."
    )
except Exception as exc:
    logging.exception("Unhandled error in interface: %s", exc)
    show_grace_message()
    st.stop()
