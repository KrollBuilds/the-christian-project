"""Streamlit chat interface for The Christian Project."""

from __future__ import annotations

# TODO: integrate Firebase Auth for user accounts
# TODO: move logs to encrypted storage (e.g., Supabase or Firestore)
# TODO: implement admin metrics dashboard for usage and cost

# Developer toggle: st.session_state["developer_mode"] = True to show tonal metrics
# TODO: Future Phase — Convert this Streamlit prototype into a FastAPI backend with REST endpoints for /query and /review.

import itertools
import json
import logging
import os
import random
import sys
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
        logging.warning("auth_utils not found; using fallback get_current_user returning None.")
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
        logging.warning("privacy_utils not found; using fallback sanitize_text that strips PII.")
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

# Preflight environment validation for Railway deployments
required_vars = ["OPENAI_API_KEY"]
missing_required = [var for var in required_vars if not os.getenv(var)]
if missing_required:
    st.error(
        "🚨 Missing required environment variables."
        f" Set the following in Railway: {', '.join(missing_required)}"
    )
    st.stop()

# Optional guards for forthcoming auth features
optional_vars = ["ACCESS_CODE", "DASHBOARD_PASSCODE"]
missing_optional = [var for var in optional_vars if not os.getenv(var)]
if missing_optional:
    logging.warning(
        "Optional secrets missing (ACCESS_CODE / DASHBOARD_PASSCODE). "
        "Features relying on them are temporarily disabled."
    )

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
REVIEW_API_URL = os.getenv(
    "REVIEW_API_URL",
    "https://the-christian-review-dashboard-production.up.railway.app/api/submit_review",
)
REVIEW_API_KEY = os.getenv("REVIEW_API_KEY")
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
        entry["submitted_by"] = sanitize_text(reviewer)

    REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with REVIEW_QUEUE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
    except OSError as exc:
        logging.exception("Unable to push response to review queue: %s", exc)
    _submit_remote_review(entry)


def _submit_remote_review(entry: Dict[str, Any]) -> None:
    if not REVIEW_API_URL:
        return

    headers = {"Content-Type": "application/json"}
    if REVIEW_API_KEY:
        headers["x-api-key"] = REVIEW_API_KEY  # align with review API authentication

    try:
        timeout = float(REVIEW_API_TIMEOUT)
    except (TypeError, ValueError):
        timeout = 5.0

    try:
        response = requests.post(
            REVIEW_API_URL,
            json=entry,
            headers=headers,
            timeout=timeout,
        )
        response.raise_for_status()
    except Exception as exc:
        logging.warning("Unable to submit response to review dashboard: %s", exc)


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

def enforce_access_code(state_key: str, prompt_label: str = "Access code") -> None:
    if not SETTINGS.get("access_control", True):
        return

    access_code = os.getenv("ACCESS_CODE")
    if not access_code:
        return

    if st.session_state.get(state_key):
        return

    st.title("The Christian Project")
    st.caption("Faithful answers for curious hearts.")
    st.markdown("### 🔑 Access Required")
    st.info("Enter the reviewer passcode provided by your administrator to continue.")

    code_key = f"{state_key}_input"
    submit_key = f"{state_key}_submit"
    code = st.text_input(prompt_label, type="password", key=code_key)
    submitted = st.button("Unlock", key=submit_key)

    if submitted:
        if code == access_code:
            st.session_state[state_key] = True
            st.session_state.pop(code_key, None)
            st.session_state.pop(submit_key, None)
            if hasattr(st, "rerun"):
                st.rerun()
            else:
                st.experimental_rerun()
        else:
            st.error("Invalid access code.")

    st.stop()

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
        layout="centered",
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
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []


st.set_page_config(
    page_title="The Christian Project",
    page_icon="✝️",
    layout="centered",
)

enforce_access_code("chat_access_granted")

st.markdown("""
<style>
/* --- Global Background & Font --- */
body, .stApp {
    background-color: #f2ede3; /* slightly deeper parchment */
    color: #1a120a;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
}

/* --- Header --- */
.stApp header, header {
    background-color: #f8f5ee;
    box-shadow: 0 3px 10px rgba(0, 0, 0, 0.1);
    border-bottom: 1px solid #d8c9b8;
}

/* --- Chat Messages --- */
.stChatMessage[data-testid="stChatMessage-User"] {
    background-color: #f8e9be;
    border: 1px solid #d6ba75;
    border-radius: 12px;
    padding: 0.9rem;
    color: #2a1e12;
    box-shadow: 0 2px 5px rgba(0, 0, 0, 0.08);
}

.stChatMessage[data-testid="stChatMessage-Assistant"] {
    background-color: #ffffff;
    border: 1px solid #e0d2be;
    border-radius: 12px;
    padding: 1rem;
    box-shadow: 0 3px 6px rgba(0, 0, 0, 0.08);
}

.stChatMessage .stMarkdown p {
    color: #2a1e12 !important;
    line-height: 1.6;
}

/* --- Inputs --- */
.stChatInput textarea,
.stTextInput>div>div>input {
    background-color: #fffdfa !important;
    color: #1b1b1b !important;
    border: 1px solid #d5c5b3 !important;
    border-radius: 8px !important;
    box-shadow: 0 1px 3px rgba(0, 0, 0, 0.05) inset;
}

.stChatInput textarea::placeholder {
    color: #8f7c67 !important;
}

/* --- Alerts & Notifications --- */
.stAlert, [data-testid="stNotification"] {
    background-color: #fff3e6 !important;
    color: #402d1a !important;
    border-left: 4px solid #d08a32 !important;
    border-radius: 10px !important;
    box-shadow: 0 2px 4px rgba(0, 0, 0, 0.06);
}

/* --- Buttons --- */
.stButton>button {
    border-radius: 8px !important;
    background-color: #c8a96f !important;
    color: #fffdfa !important;
    font-weight: 600 !important;
    border: none !important;
    padding: 0.4rem 0.9rem !important;
    box-shadow: 0 2px 3px rgba(0, 0, 0, 0.1);
    transition: all 0.15s ease-in-out;
}

.stButton>button:hover {
    background-color: #b08f56 !important;
    box-shadow: 0 3px 5px rgba(0, 0, 0, 0.15);
}

/* --- Feedback Section --- */
.feedback-wrapper {
    margin-top: 0.75rem;
    background-color: #fdf8f2;
    border: 1px solid #e0d0b6;
    padding: 0.75rem;
    border-radius: 8px;
}

.feedback-wrapper p {
    margin-bottom: 0.4rem;
    font-weight: 600;
    color: #3b2e1e;
}

/* --- Headings --- */
h1, h2, h3, h4 {
    color: #3c2c18 !important;
    font-family: "Georgia", serif;
}

/* --- Context/Expandable Boxes --- */
[data-testid="stExpander"] {
    background-color: #fffdfa !important;
    border: 1px solid #e1d3c0 !important;
    border-radius: 8px !important;
}

/* --- Mobile adjustments --- */
@media (max-width: 768px) {
    body {
        background-color: #f3ecda;
    }
    .stChatMessage[data-testid="stChatMessage-User"],
    .stChatMessage[data-testid="stChatMessage-Assistant"] {
        margin: 0.4rem 0;
    }
}
</style>

""", unsafe_allow_html=True)



RETRIEVAL_UNAVAILABLE_MSG = (
    "The retrieval system is temporarily unavailable. Please check your setup or try again later."
)


def render_header() -> None:
    st.markdown(
        """
        <header class="main-header" style="text-align:center; padding-top: 1rem;">
            <h1 style="margin-bottom: 0.25rem;">The Christian Project</h1>
            <p style="margin-top: 0; color: #6b6b6b;">Faithful answers for curious hearts.</p>
        </header>
        """,
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

            st.markdown("---")
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
    st.toast("✅ Response generated", icon="✨")


# TODO: Add persistent user sessions with login
# Review dashboard integration handled via push_for_pastoral_review

def run_chat_interface() -> None:
    render_header()
    TIMEOUT_MINUTES = 30
    now = time.time()

    if "last_activity" not in st.session_state:
        st.session_state.last_activity = now
    elif now - st.session_state.last_activity > TIMEOUT_MINUTES * 60:
        st.session_state.chat_history = []
        st.session_state.last_question = None
        st.session_state.last_submission_time = 0.0
        st.success("Session cleared due to inactivity.")
        st.toast("🧹 Conversation cleared", icon="🕊️")
    st.session_state.last_activity = now

    with st.container():
        display_chat_history()

    st.sidebar.markdown("✅ **System Status:** Online")

    if SETTINGS.get("privacy_disclaimer", True):
        st.caption(
            "⚠️ Do not share personal or identifying information. Conversations are logged anonymously for quality improvement."
        )

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


try:
    run_chat_interface()
except Exception as exc:
    logging.exception("Unhandled error in interface: %s", exc)
    show_grace_message()
    st.stop()
