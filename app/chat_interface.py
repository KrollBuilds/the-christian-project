"""Streamlit chat interface for The Christian Project."""

from __future__ import annotations

# TODO: integrate Firebase Auth for user accounts
# TODO: move logs to encrypted storage (e.g., Supabase or Firestore)
# TODO: implement admin metrics dashboard for usage and cost

# Developer toggle: st.session_state["developer_mode"] = True to show tonal metrics
# TODO: Future Phase — Convert this Streamlit prototype into a FastAPI backend with REST endpoints for /query and /review.

import json
import logging
import os
import random
import sys
from datetime import datetime, timezone
import time
from pathlib import Path
from typing import Any, Dict, List

from dotenv import load_dotenv
from openai import OpenAI

# Ensure parent directory is on the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import streamlit as st  # noqa: E402  (import after sys.path adjustment)

from app.auth_utils import get_current_user
from app.privacy_utils import sanitize_text
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
        format_truncated_answer,
        query_with_gpt,
        retrieve_contextual_sources,
        retrieve_doctrinal_sources,
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
body, .stApp {
    background-color: #f8f4ec;
    color: #1b1b1b;
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
}

.stApp header, header {
    box-shadow: 0 3px 8px rgba(0,0,0,0.08);
}

.stChatMessage[data-testid="stChatMessage-User"] {
    background-color: rgba(185, 146, 47, 0.12);
    border-radius: 12px;
    padding: 0.75rem;
}

.stChatMessage[data-testid="stChatMessage-Assistant"] {
    background-color: #fff9f3;
    border: 1px solid #e6d6c4;
    border-radius: 12px;
    padding: 0.9rem;
    box-shadow: 0 2px 6px rgba(0,0,0,0.08);
}

.stChatMessage .stMarkdown p {
    color: #2a1e12 !important;
}

.stChatInput textarea,
.stTextInput>div>div>input {
    background-color: #fff8ef !important;
    color: #1b1b1b !important;
}

.stChatInput textarea::placeholder {
    color: #a38c74 !important;
}

.stAlert, [data-testid="stNotification"] {
    background-color: #fff1e0 !important;
    color: #3b2e1e !important;
    border-radius: 10px !important;
}

.stButton>button {
    border-radius: 6px !important;
    background-color: #ece3d6 !important;
    color: #2b2118 !important;
    font-weight: 600 !important;
    border: none !important;
}

.stButton>button:hover {
    background-color: #e3d3bd !important;
}

.feedback-wrapper {
    margin-top: 0.75rem;
}

.feedback-wrapper p {
    margin-bottom: 0.4rem;
    font-weight: 600;
    color: #3b2e1e;
}

@media (max-width: 768px) {
    body {
        background-color: #f3eddd;
    }
    .stChatMessage[data-testid="stChatMessage-User"],
    .stChatMessage[data-testid="stChatMessage-Assistant"] {
        margin: 0.3rem 0;
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

            feedback_container = st.container()
            with feedback_container:
                st.markdown("<div class='feedback-wrapper'><p>Was this answer helpful?</p></div>", unsafe_allow_html=True)
            col1, col2 = st.columns([1, 1], gap="small")
            with col1:
                if st.button(
                    "👍", key=f"feedback_pos_{idx}", use_container_width=True
                ):
                    record_feedback(
                        "positive",
                        message.get("question", ""),
                        message["content"],
                    )
                    st.toast("Thank you for your feedback!", icon="✅")
            with col2:
                if st.button(
                    "👎", key=f"feedback_neg_{idx}", use_container_width=True
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


def handle_question(question: str) -> Dict[str, Any]:
    try:
        doctrine_sources = retrieve_doctrinal_sources(question, top_k=3)
    except (FileNotFoundError, ValueError):
        return {
            "role": "assistant",
            "content": RETRIEVAL_UNAVAILABLE_MSG,
            "sources": {"doctrine": [], "contextual": [], "warnings": []},
            "question": question,
        }

    warnings: List[str] = []
    try:
        contextual_sources = retrieve_contextual_sources(question, top_k=2)
    except (FileNotFoundError, ValueError) as exc:
        contextual_sources = []
        warnings.append(
            "Contextual sources unavailable. Using core doctrine only."
        )

    if not doctrine_sources:
        return {
            "role": "assistant",
            "content": (
                "I could not find doctrinal guidance for that question yet. "
                "Please try another phrasing."
            ),
            "sources": {
                "doctrine": [],
                "contextual": contextual_sources,
                "warnings": warnings,
            },
            "question": question,
        }

    result = query_with_gpt(
        question,
        doctrine_entries=doctrine_sources,
        contextual_entries=contextual_sources,
    )

    answer = result.get("answer") or ""
    warnings.extend(result.get("warnings", []))
    tone_score = result.get("tone_score")
    doctrine_sources = result.get("doctrine", doctrine_sources)
    contextual_sources = result.get("contextual", contextual_sources)

    synthesis_unavailable = any(
        answer.startswith(prefix)
        for prefix in (
            "OPENAI_API_KEY",
            "The 'openai' package",
            "OpenAI API error",
            "No context available",
        )
    )

    if synthesis_unavailable:
        warnings.append("Unable to reach the synthesis service right now.")
        lines: List[str] = ["Here are some related teachings:"]
        for item in doctrine_sources:
            lines.append(
                f"- **{item.get('question', 'N/A')}** "
                f"(score {item.get('score', 0):.2f})"
            )
        if contextual_sources:
            lines.append("")
            lines.append("Related WELS resources:")
            for item in contextual_sources:
                lines.append(
                    f"- **{item.get('title', 'N/A')}** "
                    f"(score {item.get('score', 0):.2f})"
        )
        answer = "\n".join(lines)

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
    st.toast("✅ Response generated", icon="✨")


# TODO: Add persistent user sessions with login
# TODO: Integrate with review dashboard for automatic logging

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
