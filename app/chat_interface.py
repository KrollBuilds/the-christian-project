"""
Streamlit chat interface for The Christian Project - MVP Demo Version
Combines professional HTML/CSS front-end with functional FAISS + OpenAI backend
"""

from __future__ import annotations

# ==============================================================================
# IMPORTS - NO CHANGES TO DEPENDENCIES
# ==============================================================================

import base64
import copy
import itertools
import json
import logging
import os
import random
import sys
import textwrap
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
import streamlit as st
from dotenv import load_dotenv
from openai import OpenAI

# Ensure parent directory is on the Python path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Import auth utilities with fallback
try:
    from .auth_utils import get_current_user  # type: ignore
except Exception:
    try:
        from app.auth_utils import get_current_user  # type: ignore
    except Exception:
        logging.debug("auth_utils not found; defaulting get_current_user to None.")
        def get_current_user():
            return None

# Import privacy utilities with fallback
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
            text = re.sub(r"\b[\w.%+-]+@[\w.-]+\.[a-zA-Z]{2,}\b", "[redacted email]", text)
            text = re.sub(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?){1,2}\d{4}\b", "[redacted phone]", text)
            return text.strip()

from config import SETTINGS

load_dotenv()

# ==============================================================================
# CONFIGURATION & ENVIRONMENT SETUP
# ==============================================================================

# Preflight environment validation
required_vars = ["OPENAI_API_KEY"]
missing_required = [var for var in required_vars if not os.getenv(var)]
if missing_required:
    st.error(
        f"🚨 Missing required environment variables: {', '.join(missing_required)}"
    )
    st.stop()

# Configure logging
logging.basicConfig(level=logging.INFO)
logging.info("🚀 Starting The Christian Project - MVP Demo Version")

# Ensure Hugging Face cache uses mounted storage
os.environ["HF_HOME"] = os.environ.get("HF_HOME", "data/cache")
os.environ["TOKENIZERS_PARALLELISM"] = "false"

# Ensure required data directories exist
DATA_PATHS = [
    Path("data/feedback"),
    Path("data/metrics"),
    Path("data/processed/vector_store"),
    Path("logs"),
]
for path in DATA_PATHS:
    path.mkdir(parents=True, exist_ok=True)

# Configuration paths and URLs
FEEDBACK_LOG_PATH = Path("data/metrics/feedback_log.jsonl")
REVIEW_QUEUE_PATH = Path(os.getenv("REVIEW_QUEUE_PATH", "data/metrics/review_queue.jsonl"))
DEFAULT_REVIEW_API_URL = "https://the-christian-review-dashboard-production.up.railway.app/api/submit_review"

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

REVIEW_API_URL = _first_non_empty(
    os.getenv("REVIEW_API_URL"),
    _get_streamlit_secret("review_api_url"),
    DEFAULT_REVIEW_API_URL,
)

REVIEW_API_KEY_HEADER = _first_non_empty(
    os.getenv("REVIEW_API_KEY"),
    os.getenv("REVIEW_DASHBOARD_KEY"),
    _get_streamlit_secret("review_api_key"),
)

REVIEW_API_SHARED_SECRET = _first_non_empty(
    os.getenv("REVIEW_API_SECRET"),
    os.getenv("REVIEW_SHARED_SECRET"),
    _get_streamlit_secret("review_api_secret"),
)

REVIEW_API_BEARER_TOKEN = _first_non_empty(
    os.getenv("REVIEW_API_BEARER_TOKEN"),
    _get_streamlit_secret("review_api_bearer_token"),
)

REVIEW_API_TIMEOUT = os.getenv("REVIEW_API_TIMEOUT", "5")

# OpenAI Configuration
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.error("⚠️ OpenAI API key not found. Please set OPENAI_API_KEY environment variable.")
    st.stop()

client = OpenAI(api_key=OPENAI_API_KEY)

if REVIEW_API_KEY_HEADER:
    logging.info("Review API authentication configured.")
else:
    logging.info("Review API key not configured; remote submissions may be rejected.")

# ==============================================================================
# CONSTANTS & HELPER DATA
# ==============================================================================

GRACE_MESSAGES = [
    ("Sorry, we're experiencing difficulties. Thank you for your patience.", "Romans 8:28"),
    ("Something went wrong, but God's plan never fails.", "Jeremiah 29:11"),
    ("Our system stumbled — faith reminds us we'll get back up.", "2 Corinthians 12:9"),
    ("Please try again soon. The Lord is near to those who wait in hope.", "Psalm 130:5"),
]

LOADING_VERSES = itertools.cycle([
    "Be still, and know that I am God. — Psalm 46:10",
    "The Lord is my light and my salvation. — Psalm 27:1",
    "Those who hope in the Lord will renew their strength. — Isaiah 40:31",
    "The Lord is faithful to all His promises. — Psalm 145:13",
])

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
            "such as Psalm 63 or the Lord's Prayer (Matthew 6:9-13). Begin with thanksgiving, bring your requests "
            "honestly, and close by asking the Spirit to keep you mindful of Christ throughout the day. "
            "If a day is missed, return without shame; grace fuels consistency more than guilt ever can."
        ),
        "sources": {},
        "question": "How can I build a daily rhythm of prayer that stays consistent?",
        "example": True,
    },
]

# ==============================================================================
# BACK-END (AI RESPONSE LOGIC)
# ==============================================================================

def show_grace_message() -> None:
    """Display a graceful error message with Scripture"""
    message, verse = random.choice(GRACE_MESSAGES)
    st.warning(f"🙏 {message}\n\n**{verse}**")

def record_feedback(rating: str, question: str, answer: str) -> None:
    """Record user feedback to local log"""
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
    """Queue response for pastoral review"""
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

    # Save locally
    REVIEW_QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        with REVIEW_QUEUE_PATH.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(entry, ensure_ascii=True) + "\n")
        logging.debug("Queued response %s locally for review.", response_id)
    except OSError as exc:
        logging.exception("Unable to push response to review queue: %s", exc)
    
    # Submit remotely
    if not _submit_remote_review(entry):
        logging.warning("Remote pastoral review submission failed for %s.", response_id)

def _build_review_headers() -> Dict[str, str]:
    """Build HTTP headers for review API"""
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
    """Build payload for review API"""
    payload = dict(entry)
    secret = REVIEW_API_SHARED_SECRET or REVIEW_API_BEARER_TOKEN
    if secret:
        payload.setdefault("secret", secret)
        payload.setdefault("api_secret", secret)
    if REVIEW_API_KEY_HEADER:
        payload.setdefault("api_key", REVIEW_API_KEY_HEADER)
    return payload

def _submit_remote_review(entry: Dict[str, Any]) -> bool:
    """Submit review entry to remote dashboard"""
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
    """
    Core OpenAI synthesis function - DO NOT MODIFY
    Generates theologically aligned response using GPT
    """
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

# Import FAISS retrieval functions - DO NOT MODIFY
try:
    from scripts.query_rag import (
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
    st.error(
        "⚠️ Unable to load retrieval utilities. Please verify the `scripts` package is present."
    )
    st.caption(f"Debug detail: {exc}")
    st.stop()

def _fallback_from_retrieval(
    doctrine_sources: List[Dict[str, Any]],
    contextual_sources: List[Dict[str, Any]],
) -> str:
    """Fallback response when synthesis fails but retrieval succeeds"""
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
    """
    Core question handling function - DO NOT MODIFY
    Orchestrates FAISS retrieval + OpenAI synthesis
    """
    # Retrieve from doctrinal sources
    try:
        doctrine_sources = retrieve_doctrinal_sources(question, top_k=3)
    except (FileNotFoundError, ValueError) as exc:
        logging.exception("Doctrinal retrieval failed: %s", exc)
        doctrine_sources = []

    # Retrieve from contextual sources
    warnings: List[str] = []
    try:
        contextual_sources = retrieve_contextual_sources(question, top_k=2)
    except (FileNotFoundError, ValueError) as exc:
        logging.exception("Contextual retrieval failed: %s", exc)
        contextual_sources = []
        warnings.append("Contextual sources unavailable. Using core doctrine only.")

    # Build context for LLM
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

    # Synthesize response with OpenAI
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

def get_ai_response(user_input: str) -> str:
    """
    API BRIDGE FUNCTION - Simple wrapper for HTML/external access
    Takes a question string, returns answer string
    """
    try:
        response_dict = handle_question(user_input)
        return response_dict.get("content", "I apologize, but I couldn't generate a response.")
    except Exception as exc:
        logging.exception("Error in get_ai_response: %s", exc)
        return "I apologize, but an error occurred. Please try again or contact support."

# ==============================================================================
# FRONT-END (HTML EMBED & UI)
# ==============================================================================

def load_html_mockup() -> str:
    """Load the HTML mockup file"""
    mockup_path = Path("christian_project_mockup.html")
    if not mockup_path.exists():
        return """
        <div style='text-align:center; padding:2rem;'>
            <h2>HTML Mockup Not Found</h2>
            <p>Please ensure 'christian_project_mockup.html' is in the same directory as this script.</p>
        </div>
        """
    try:
        with open(mockup_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as exc:
        logging.exception("Failed to load HTML mockup: %s", exc)
        return f"""
        <div style='text-align:center; padding:2rem;'>
            <h2>Error Loading Mockup</h2>
            <p>{str(exc)}</p>
        </div>
        """

def inject_custom_css() -> None:
    """Inject custom CSS for Streamlit UI to match mockup styling"""
    st.markdown("""
    <style>
    /* Design tokens matching HTML mockup */
    :root {
        --color-navy-deep: #1e3a8a;
        --color-gold-soft: #f4e3b2;
        --color-parchment: #faf7f0;
        --color-charcoal: #111827;
        --color-page-bg: #f5f1e8;
    }
    
    /* Page background */
    .stApp {
        background-color: var(--color-page-bg);
    }
    
    /* Chat messages */
    .stChatMessage[data-testid="user-message"] {
        background-color: #e8e3d8;
        border-radius: 12px 12px 4px 12px;
    }
    
    .stChatMessage[data-testid="assistant-message"] {
        background-color: white;
        border: 1px solid #d1c4a8;
        border-radius: 12px 12px 12px 4px;
    }
    
    /* Input styling */
    .stChatInput {
        border-color: #d1c4a8;
        background-color: var(--color-parchment);
    }
    
    /* Headers */
    h1, h2, h3 {
        font-family: "Merriweather Sans", sans-serif;
        color: var(--color-navy-deep);
    }
    
    /* Body text */
    p, .stMarkdown {
        font-family: Georgia, serif;
        color: var(--color-charcoal);
        line-height: 1.75;
    }
    
    /* Button styling */
    .stButton button {
        background-color: var(--color-navy-deep);
        color: white;
        border-radius: 8px;
        font-weight: 600;
    }
    
    .stButton button:hover {
        background-color: #1e40af;
    }
    
    /* Hide Streamlit branding for demo */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    </style>
    """, unsafe_allow_html=True)

# ==============================================================================
# SESSION STATE & INITIALIZATION
# ==============================================================================

def initialize_session_state() -> None:
    """Initialize all session state variables"""
    if "chat_history" not in st.session_state:
        st.session_state.chat_history = copy.deepcopy(EXAMPLE_CONVERSATION)
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
    if "show_html_mockup" not in st.session_state:
        st.session_state.show_html_mockup = True

def reset_conversation() -> None:
    """Clear conversation history and start fresh"""
    st.session_state.chat_history = []
    st.session_state.last_question = None
    st.session_state.last_submission_time = 0.0
    st.session_state.pending_question = None
    st.session_state.is_generating = False
    st.session_state.pop("chat_input", None)

# ==============================================================================
# INPUT PROCESSING
# ==============================================================================

def process_input(user_input_raw: str) -> None:
    """Process user input and trigger response generation"""
    user_input = user_input_raw.strip()
    if not user_input:
        return

    if st.session_state.get("is_generating"):
        st.warning("Please wait for the current response to finish.")
        return

    # Prevent duplicate submissions
    if user_input == st.session_state.last_question:
        st.stop()

    # Rate limiting
    current_time = time.time()
    if current_time - st.session_state.last_submission_time < 1:
        st.warning("Please wait a moment before submitting another question.")
        st.stop()

    st.session_state.last_submission_time = current_time
    st.session_state.last_question = user_input

    # Add user message
    st.session_state.chat_history.append({
        "role": "user",
        "content": user_input,
        "question": user_input
    })

    # Add pending assistant message
    st.session_state.chat_history.append({
        "role": "assistant",
        "content": "",
        "question": user_input,
        "sources": {},
        "pending": True,
    })

    st.session_state.pending_question = user_input
    st.session_state.is_generating = True

    if hasattr(st, "rerun"):
        st.rerun()
    else:
        st.experimental_rerun()

def resolve_pending_generation() -> None:
    """Generate response for pending question"""
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
        with st.spinner("Reflecting on your question..."):
            assistant_message = handle_question(question)
    except Exception as exc:
        logging.exception("Error while generating response: %s", exc)
        show_grace_message()
        st.session_state.last_question = None
        assistant_message = None
    finally:
        st.session_state._generation_lock = False

    if assistant_message:
        # Replace pending message with actual response
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
        # Remove pending message on failure
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

# ==============================================================================
# STREAMLIT APP ENTRYPOINT
# ==============================================================================

def run_chat_interface() -> None:
    """Main application entry point"""
    
    # Page configuration
    st.set_page_config(
        page_title="The Christian Project - MVP Demo",
        page_icon="✝️",
        layout="wide",
        initial_sidebar_state="collapsed",
    )
    
    # Initialize
    initialize_session_state()
    inject_custom_css()
    
    # --- OPTIONAL: HTML MOCKUP DISPLAY ---
    # Toggle to show/hide HTML mockup for stakeholder demo
    with st.sidebar:
        st.markdown("## 🎨 Demo Options")
        show_mockup = st.checkbox(
            "Show HTML Design Mockup",
            value=st.session_state.show_html_mockup,
            help="Display the professional HTML/CSS mockup above the functional chat"
        )
        st.session_state.show_html_mockup = show_mockup
        
        st.markdown("---")
        st.markdown("## 🕊️ Conversation")
        if st.button("Clear Chat", use_container_width=True):
            reset_conversation()
            st.toast("🕊️ Conversation cleared")
            st.rerun()
        
        st.markdown("---")
        st.caption("**The Christian Project** - MVP Demo Version")
        st.caption("Backend: FAISS + OpenAI")
        st.caption("Frontend: HTML/CSS + Streamlit")
    
    # Display HTML mockup if enabled
    if st.session_state.show_html_mockup:
        st.markdown("### 🎨 Professional Design Preview")
        st.caption("This is the HTML/CSS mockup. The functional chat is below.")
        html_content = load_html_mockup()
        st.components.v1.html(html_content, height=800, scrolling=True)
        st.stop()
        st.markdown("---")
    
    # --- FUNCTIONAL CHAT INTERFACE ---
    st.markdown("## ✝️ The Christian Project")
    st.caption("Ask questions grounded in Scripture and Lutheran theology")
    
    # Trust panel
    st.info(
        "**Guidance:** Please don't include personal details. "
        "Responses are grounded in Scripture and Lutheran teaching. "
        "For personal spiritual care, please speak with your pastor."
    )
    
    # Display chat history
    for message in st.session_state.chat_history:
        role = message.get("role", "assistant")
        content = message.get("content", "")
        is_pending = message.get("pending", False)
        is_example = message.get("example", False)
        
        with st.chat_message(role):
            if is_pending:
                st.markdown("*Reflecting on your question...*")
            else:
                st.markdown(content)
            
            # Show sources for non-example assistant messages
            if role == "assistant" and not is_example and not is_pending:
                sources = message.get("sources", {})
                doctrine_sources = sources.get("doctrine", [])
                contextual_sources = sources.get("contextual", [])
                
                if doctrine_sources or contextual_sources:
                    with st.expander("📚 Sources Consulted"):
                        if doctrine_sources:
                            st.markdown("**Doctrinal Sources:**")
                            for item in doctrine_sources:
                                st.markdown(
                                    f"- {item.get('question', 'N/A')} "
                                    f"(score: {item.get('score', 0):.2f})"
                                )
                        
                        if contextual_sources:
                            st.markdown("**Contextual Sources:**")
                            for item in contextual_sources:
                                title = item.get('title', 'N/A')
                                url = item.get('url')
                                link = f"[{title}]({url})" if url else title
                                st.markdown(
                                    f"- {link} "
                                    f"(score: {item.get('score', 0):.2f})"
                                )
    
    # Handle pending generation
    if st.session_state.get("is_generating"):
        resolve_pending_generation()
        return
    
    # Chat input
    user_input = st.chat_input(
        "Ask your theological question here...",
        key="chat_input"
    )
    
    if user_input:
        process_input(user_input)
    
    # Disclaimer
    st.markdown("---")
    st.caption(
        "💬 *For personal or spiritual matters, please speak with your pastor or spiritual advisor.*"
    )

# ==============================================================================
# RUN APPLICATION
# ==============================================================================

if __name__ == "__main__":
    try:
        run_chat_interface()
        logging.info("MVP demo interface running successfully.")
    except Exception as exc:
        logging.exception("Unhandled error in interface: %s", exc)
        show_grace_message()
        st.stop()