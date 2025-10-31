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

import streamlit as st
with open("christian_project_mockup.html") as f:
    st.components.v1.html(f.read(), height=900, scrolling=True)
 # noqa: E402  (import after sys.path adjustment)

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
    from app.config import apply_theme_to_dom, current_theme, ensure_theme, sync_toggle_state
    from app.ui.layout import render_shell
    from app.ui.widgets import (
        MessageMeta,
        accessible_button,
        render_message_bubble,
        render_skeleton_message,
    )
except ImportError:  # pragma: no cover - fallback when package context unavailable
    from .config import apply_theme_to_dom, current_theme, ensure_theme, sync_toggle_state  # type: ignore
    from .ui.layout import render_shell  # type: ignore
    from .ui.widgets import (  # type: ignore
        MessageMeta,
        accessible_button,
        render_message_bubble,
        render_skeleton_message,
    )

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
    return "✝️"

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
        ['description', 'Faithful answers for curious hearts.']
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

EXAMPLE_CONVERSATION = [
    {
        "role": "user",
        "content": "How can I build a daily rhythm of prayer that stays consistent?",
        "question": "How can I build a daily rhythm of prayer that stays consistent?",
        "example": True,
    },
    {
        "role": "assistant",
        "content": (
            "A steady prayer rhythm grows when you anchor it to Scripture and simple habits. "
            "Set aside a predictable time—morning coffee or evening wind-down—and pair it with a short reading "
            "such as Psalm 63 or the Lord’s Prayer (Matthew 6:9-13). Begin with thanksgiving, bring your requests "
            "honestly, and close by asking the Spirit to keep you mindful of Christ throughout the day. "
            "If a day is missed, return without shame; grace fuels consistency more than guilt ever can."
        ),
        "sources": {},
        "question": "How can I build a daily rhythm of prayer that stays consistent?",
        "example": True,
    },
]


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
    if assistant_payload.get("example"):
        return

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
        "⚠️ Unable to load retrieval utilities. Please verify the `scripts` package is present and importable."
    )
    st.caption(f"Debug detail: {exc}")
    st.stop()



RETRIEVAL_UNAVAILABLE_MSG = (
    "The retrieval system is temporarily unavailable. Please check your setup or try again later."
)

def _initialize_ui_state() -> None:
    ensure_theme()
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = []
    if "conversation_archive" not in st.session_state:
        st.session_state.conversation_archive = {}
    if "show_about_modal" not in st.session_state:
        st.session_state.show_about_modal = False
    if "last_question" not in st.session_state:
        st.session_state.last_question = None
    if "last_submission_time" not in st.session_state:
        st.session_state.last_submission_time = 0.0
    if "pending_question" not in st.session_state:
        st.session_state.pending_question = None
    if "is_generating" not in st.session_state:
        st.session_state.is_generating = False
    if "_generation_lock" not in st.session_state:
        st.session_state._generation_lock = False
    if "ui_theme_toggle" not in st.session_state:
        st.session_state.ui_theme_toggle = current_theme() == "dark"
    if "pending_grace_message" not in st.session_state:
        st.session_state.pending_grace_message = False
    if not st.session_state.chat_history:
        st.session_state.chat_history = copy.deepcopy(EXAMPLE_CONVERSATION)


def reset_conversation() -> None:
    st.session_state.chat_history = []
    st.session_state.last_question = None
    st.session_state.last_submission_time = 0.0
    st.session_state.last_activity = time.time()
    st.session_state.pending_question = None
    st.session_state.is_generating = False
    st.session_state.pop("user_input", None)
    st.session_state.pop("chat_question", None)


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
    logo_src = _resolve_logo_src("primary")
    logo_srcset_candidate = _resolve_logo_src("large")
    logo_srcset = ""
    if logo_srcset_candidate and logo_srcset_candidate != logo_src:
        logo_srcset = f' srcset="{logo_src} 1x, {logo_srcset_candidate} 2x"'

    st.markdown(
        f"""
        <div class="tcp-sidebar__brand">
            <img src="{logo_src}"{logo_srcset} alt="The Christian Project logo" width="52" height="52" loading="lazy" decoding="async" />
            <div class="tcp-sidebar__brand-title">The Christian Project</div>
            <div class="tcp-sidebar__brand-subtitle">Faithful answers for curious hearts.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    st.markdown('<section class="tcp-sidebar__section">', unsafe_allow_html=True)
    st.markdown('<h2 class="tcp-sidebar__section-title">🕊️ New Chat</h2>', unsafe_allow_html=True)
    st.markdown(
        "<p class='tcp-sidebar__body-text'>Clear the current dialogue and start fresh with a new theological question.</p>",
        unsafe_allow_html=True,
    )
    if accessible_button(
        "Start new conversation",
        key="sidebar_new_chat",
        aria_label="Start a new theological conversation",
        icon="🆕",
    ):
        reset_conversation()
        st.toast("🕊️ Conversation cleared. Ready for a new question.")
        if hasattr(st, "rerun"):
            st.rerun()
        else:
            st.experimental_rerun()
    st.markdown("</section>", unsafe_allow_html=True)

    st.markdown('<section class="tcp-sidebar__section">', unsafe_allow_html=True)
    st.markdown('<h2 class="tcp-sidebar__section-title">📜 About the Project</h2>', unsafe_allow_html=True)
    st.markdown(
        "<p class='tcp-sidebar__body-text'>A prototype assistant offering confessional Lutheran answers from curated doctrine and contextual resources.</p>",
        unsafe_allow_html=True,
    )
    if accessible_button(
        "Read guidance",
        key="open_about_modal",
        aria_label="Open About and guidance information",
        icon="ℹ️",
    ):
        st.session_state.show_about_modal = True
        if hasattr(st, "rerun"):
            st.rerun()
        else:
            st.experimental_rerun()
    st.markdown("</section>", unsafe_allow_html=True)

    st.markdown('<section class="tcp-sidebar__section">', unsafe_allow_html=True)
    st.markdown('<h2 class="tcp-sidebar__section-title">🌓 Toggle Theme</h2>', unsafe_allow_html=True)
    toggle_value = st.toggle(
        "Enable dark theme",
        key="ui_theme_toggle",
        value=st.session_state.get("ui_theme_toggle", current_theme() == "dark"),
        help="Switch between light and dark reading modes.",
    )
    sync_toggle_state(toggle_value)
    apply_theme_to_dom()
    st.caption("Theme preference stays active while this tab remains open.")
    st.markdown("</section>", unsafe_allow_html=True)

    st.markdown('<section class="tcp-sidebar__section">', unsafe_allow_html=True)
    st.markdown('<h2 class="tcp-sidebar__section-title">💬 Feedback</h2>', unsafe_allow_html=True)
    st.markdown(
        "<p class='tcp-sidebar__body-text'>Feedback collection is on the roadmap. Share thoughts with the pastoral team soon.</p>",
        unsafe_allow_html=True,
    )
    if accessible_button(
        "Feedback (coming soon)",
        key="sidebar_feedback",
        aria_label="Leave feedback (coming soon)",
        icon="💬",
    ):
        st.toast("Feedback collection is coming soon.", icon="📝")
    st.markdown("</section>", unsafe_allow_html=True)


def render_trust_panel() -> None:
    st.markdown(
        """
        <div class="tcp-trust-panel" role="note" aria-label="Guidance for asking questions">
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
        f"""
        <header class="tcp-main__header">
            <div class="tcp-main__header-copy">
                <h1>Ask with confidence</h1>
                <p>Use the example conversation below or send your own question to begin.</p>
            </div>
        </header>
        """,
        unsafe_allow_html=True,
    )


def display_chat_history() -> None:
    st.markdown(
        '<div id="tcp-chat-log" class="tcp-messages" role="log" aria-live="polite" aria-label="Conversation transcript">',
        unsafe_allow_html=True,
    )
    for idx, message in enumerate(st.session_state.get("chat_history", [])):
        role = message.get("role", "assistant")
        is_example = message.get("example", False)
        meta = MessageMeta(
            role=role,
            pending=message.get("pending", False),
            message_id=f"tcp-message-{idx}",
            aria_label=message.get("aria_label"),
        )
        message_container = st.container()
        with message_container:
            bubble_container = render_message_bubble(
                message.get("content", " "),
                meta,
                container=message_container,
            )

            if meta.pending:
                render_skeleton_message(container=bubble_container)
                continue

            if role != "assistant":
                continue

            if is_example:
                continue

            sources = message.get("sources", {})
            doctrine_sources = sources.get("doctrine", [])
            contextual_sources = sources.get("contextual", [])
            warnings = sources.get("warnings", [])
            tone_score = sources.get("tone_score")

            if doctrine_sources or contextual_sources:
                with bubble_container.expander("Sources consulted", expanded=False):
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

            col1, col2 = st.columns([1, 1], gap="medium")
            with col1:
                if st.button(
                    "👍 Helpful",
                    key=f"feedback_pos_{idx}",
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
                    key=f"feedback_neg_{idx}",
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
        """
        <script>
        (function() {
            const doc = window.parent?.document || document;
            const region = doc.getElementById("tcp-chat-log");
            if (region) {
                region.scrollTop = region.scrollHeight;
            }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )


def render_chat_input() -> None:
    disabled = st.session_state.get("is_generating", False)
    st.markdown('<div class="tcp-chat-input-shell">', unsafe_allow_html=True)
    with st.form("chat_composer", clear_on_submit=True):
        st.markdown(
            '<div class="tcp-chat-input" role="form" aria-label="Compose a new theological question">',
            unsafe_allow_html=True,
        )
        message = st.text_input(
            "Type your question here... Press Enter to send",
            key="chat_composer_text",
            placeholder="Type your question here... Press Enter to send",
            label_visibility="collapsed",
            disabled=disabled,
        )
        send = st.form_submit_button(
            "Send ✈️",
            use_container_width=True,
            disabled=disabled or not message.strip(),
        )
        st.markdown("</div>", unsafe_allow_html=True)
    st.markdown(
        """
        <script>
        (function() {
            const doc = window.parent?.document ?? document;
            if (!doc) {
                return;
            }
            const button = doc.querySelector('form#chat_composer button');
            if (button) {
                button.setAttribute('aria-label', 'Send message');
                button.setAttribute('tabindex', '0');
            }
        })();
        </script>
        """,
        unsafe_allow_html=True,
    )
    st.markdown("</div>", unsafe_allow_html=True)

    if disabled:
        return

    if send:
        text = message.strip()
        if not text:
            st.warning("Please add a question before sending.")
            return
        process_input(text)


def _fallback_from_retrieval(
    doctrine_sources: List[Dict[str, Any]],
    contextual_sources: List[Dict[str, Any]],
) -> str:
    if not doctrine_sources and not contextual_sources:
        message = "Faithful resources are still being gathered for this topic. Please check back soon."
        return append_pastoral_guidance(message)

    def _display_label(entry: Dict[str, Any], *, default: str = "Doctrinal reference") -> str:
        for key in ("question", "title", "heading", "topic"):
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        fallback = entry.get("id") or entry.get("chunk_id")
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip()
        return default

    lines: List[str] = ["Here are some related teachings:"]
    for item in doctrine_sources:
        lines.append(
            f"- **{_display_label(item)}** (score {item.get('score', 0):.2f})"
        )
    if contextual_sources:
        lines.append("")
        lines.append("Related WELS resources:")
        for item in contextual_sources:
            lines.append(
                f"- **{_display_label(item, default='Contextual resource')}** (score {item.get('score', 0):.2f})"
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

    if st.session_state.get("is_generating"):
        st.warning("Please wait for the current response to finish.")
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

    st.session_state.chat_history.append(
        {"role": "user", "content": user_input, "question": user_input}
    )
    st.session_state.chat_history.append(
        {
            "role": "assistant",
            "content": "",
            "question": user_input,
            "sources": {},
            "pending": True,
        }
    )
    st.session_state.pending_question = user_input
    st.session_state.is_generating = True

    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


def _resolve_pending_generation() -> None:
    if not st.session_state.get("is_generating"):
        return
    question = st.session_state.get("pending_question")
    if not question:
        st.session_state.is_generating = False
        return
    if st.session_state.get("_generation_lock"):
        return

    st.session_state._generation_lock = True
    try:
        with st.spinner("The Christian Project is reflecting…"):
            assistant_message = handle_question(question)
    except Exception as exc:
        logging.exception("Error while generating response: %s", exc)
        st.session_state.pending_grace_message = True
        st.session_state.last_question = None
        assistant_message = None
    finally:
        st.session_state._generation_lock = False

    if assistant_message:
        for idx in range(len(st.session_state.chat_history) - 1, -1, -1):
            entry = st.session_state.chat_history[idx]
            if entry.get("pending"):
                updated = dict(assistant_message)
                updated.pop("pending", None)
                st.session_state.chat_history[idx] = updated
                break
        push_for_pastoral_review(question, assistant_message)
        st.toast("✅ Response generated", icon="✨")
    else:
        for idx in range(len(st.session_state.chat_history) - 1, -1, -1):
            entry = st.session_state.chat_history[idx]
            if entry.get("pending"):
                st.session_state.chat_history.pop(idx)
                break

    st.session_state.pending_question = None
    st.session_state.is_generating = False
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()


# Review dashboard integration handled via push_for_pastoral_review

def run_chat_interface() -> None:
    _initialize_ui_state()
    inject_pwa_metadata()
    TIMEOUT_MINUTES = 30
    now = time.time()

    if "last_activity" not in st.session_state:
        st.session_state.last_activity = now
    elif now - st.session_state.last_activity > TIMEOUT_MINUTES * 60:
        reset_conversation()
        st.info("Session cleared after a quiet pause. Ready whenever you are.")
        st.toast("🧹 Conversation cleared", icon="🕊️")
    st.session_state.last_activity = time.time()

    def _render_sidebar() -> None:
        render_sidebar()

    def _render_main() -> None:
        if st.session_state.get("pending_grace_message"):
            show_grace_message()
            st.session_state.pending_grace_message = False
        render_main_header()
        render_trust_panel()
        display_chat_history()
        render_chat_input()

    render_shell(_render_sidebar, _render_main)

    if st.session_state.get("is_generating"):
        _resolve_pending_generation()
        return

    user_input = st.chat_input(
        "Ask a theological question...", key="chat_question", placeholder="How can we pray for those who doubt?"
    )

    if user_input:
        process_input(user_input)

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
