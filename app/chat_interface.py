"""Streamlit chat interface for The Christian Project."""

from __future__ import annotations

# TODO: integrate Firebase Auth for user accounts
# TODO: move logs to encrypted storage (e.g., Supabase or Firestore)
# TODO: implement admin metrics dashboard for usage and cost

# Developer toggle: st.session_state["developer_mode"] = True to show tonal metrics

import json
import logging
import os
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
required_vars = ["OPENAI_API_KEY", "ACCESS_CODE", "DASHBOARD_PASSCODE"]
missing_vars = [var for var in required_vars if not os.getenv(var)]
if missing_vars:
    sys.exit(f"Missing environment variables: {', '.join(missing_vars)}")

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

# To set key locally: echo "OPENAI_API_KEY=yourkey" > .env
# For deployment: add OPENAI_API_KEY as an environment variable in the hosting platform.
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("⚠️ OpenAI API key not found. Please set it in your environment or a .env file.")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)
# TODO: Secure key handling for multi-user hosting (user tokens vs global key).

os.environ["TOKENIZERS_PARALLELISM"] = "false"


def enforce_access_code(state_key: str, prompt_label: str = "Access code") -> None:
    if not SETTINGS.get("access_control", True):
        return
    access_code = os.getenv("ACCESS_CODE")
    if not access_code:
        return
    if st.session_state.get(state_key):
        return

    code_key = f"{state_key}_input"
    code = st.text_input(prompt_label, type="password", key=code_key)
    if not code:
        st.stop()
    if code != access_code:
        st.error("Invalid access code.")
        st.stop()
    st.session_state[state_key] = True
    st.session_state.pop(code_key, None)
    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

try:
    from scripts.query_rag import (  # noqa: E402
        format_truncated_answer,
        query_with_gpt,
        retrieve_contextual_sources,
        retrieve_doctrinal_sources,
    )
except Exception:
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
    st.stop()


# Safeguard session state directly after imports
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "feedback_log" not in st.session_state:
    st.session_state.feedback_log = []


st.set_page_config(
    page_title="The Christian Project",
    page_icon="✝️",
    layout="centered",
)

enforce_access_code("chat_access_granted")

st.markdown("""
<style>
/* Base layout */
body, .stApp {
    background-color: #f6f2e7;        /* slightly deeper parchment */
    color: #1b1b1b;                   /* strong neutral text */
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
}
header {
    box-shadow: 0 2px 4px rgba(0,0,0,0.08);
}

/* Chat container */
.chat-container {
    max-width: 720px;
    margin: 0 auto;
    padding: 1.5rem 1rem 5rem 1rem;
}

/* Chat bubbles */
.chat-bubble {
    padding: 1rem 1.2rem;
    border-radius: 18px;
    margin-bottom: 0.9rem;
    line-height: 1.6;
    word-wrap: break-word;
    box-shadow: 0px 2px 8px rgba(0,0,0,0.10);
}

/* USER (gold → deeper bronze) */
.chat-bubble.user {
    background-color: #b9922f;       /* richer bronze-gold */
    color: #fffdf5;                  /* off-white text for contrast */
    margin-left: 20%;
    border-top-right-radius: 6px;
}

/* ASSISTANT (soft cream) */
.chat-bubble.assistant {
    background-color: #fffaf0;       /* light warm cream */
    color: #141414;                  /* deep black-brown text */
    margin-right: 20%;
    border-top-left-radius: 6px;
    border: 1px solid #e0dac3;
    line-height: 1.7;
}

/* Feedback buttons */
.feedback-buttons button {
    margin-right: 0.5rem;
    background-color: #2c2c2c !important;
    color: #ffffff !important;
    border-radius: 8px !important;
    font-size: 0.9rem !important;
}
.feedback-buttons button:hover {
    background-color: #d4af37 !important;
    color: #0c0c0c !important;
}

/* “Context used” + warnings */
.stAlert, [data-testid="stNotification"] {
    background-color: #fffaf0 !important;
    color: #111111 !important;
}

/* Ensure chat messages use dark text for readability */
.stChatMessage .stMarkdown,
.stChatMessage p,
.stChatMessage li,
.stChatMessage span,
.stChatMessage pre,
.stChatMessage code {
    color: #000000 !important;
}


/* Responsive */
@media (max-width: 768px) {
    body {
        background-color: #f3eddd;
    }
    .chat-bubble.user, .chat-bubble.assistant {
        margin: 0.3rem 0;
    }
}
</style>
""", unsafe_allow_html=True)



RETRIEVAL_UNAVAILABLE_MSG = (
    "The retrieval system is temporarily unavailable. Please check your setup or try again later."
)


def ensure_feedback_log() -> Path:
    feedback_dir = Path("data") / "feedback"
    feedback_dir.mkdir(parents=True, exist_ok=True)
    return feedback_dir / "feedback_log.json"


def append_feedback(entry: Dict[str, Any]) -> None:
    log_path = ensure_feedback_log()
    if log_path.exists():
        with log_path.open("r", encoding="utf-8") as log_file:
            try:
                feedback_data = json.load(log_file)
            except json.JSONDecodeError:
                feedback_data = []
    else:
        feedback_data = []

    sanitized_entry = {
        "question": sanitize_text(entry.get("question")),
        "answer": sanitize_text(entry.get("answer")),
        "timestamp": entry.get("timestamp"),
        "feedback": sanitize_text(entry.get("feedback")),
        "user_id": get_current_user(),
    }

    feedback_data.append(sanitized_entry)
    with log_path.open("w", encoding="utf-8") as log_file:
        json.dump(feedback_data, log_file, ensure_ascii=True, indent=2)

    st.session_state.feedback_log.append(sanitized_entry)


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

            col1, col2 = st.columns([1, 1], gap="small")
            with col1:
                if st.button(
                    "👍", key=f"feedback_pos_{idx}", use_container_width=True
                ):
                    append_feedback(
                        {
                            "question": message.get("question", ""),
                            "answer": message["content"],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "feedback": "positive",
                        }
                    )
                    st.toast("Thank you for the feedback!", icon="✅")
            with col2:
                if st.button(
                    "👎", key=f"feedback_neg_{idx}", use_container_width=True
                ):
                    append_feedback(
                        {
                            "question": message.get("question", ""),
                            "answer": message["content"],
                            "timestamp": datetime.now(timezone.utc).isoformat(),
                            "feedback": "negative",
                        }
                    )
                    st.toast("Feedback recorded.", icon="✍️")

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
        st.error("⚠️ Something went wrong while generating a response. Please try again.")
        print(f"Internal error: {exc}")
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
    st.error("⚠️ Something went wrong while generating a response. Please try again.")
    print(f"Internal error: {exc}")
    st.stop()
