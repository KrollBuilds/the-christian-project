"""Shared helpers for the reviewer portal pages."""

from __future__ import annotations

import json
import os
import uuid
from typing import Optional, Set

from dotenv import load_dotenv
import streamlit as st

load_dotenv()

BACKGROUND_STYLE = """
<style>
body, .stApp {
    background-color: #f8f6f1;
    color: #2a1e12;
    font-family: "Georgia", "Times New Roman", serif;
}

/* Headings and markdown text */
h1, h2, h3, h4, h5, h6, p, label, span, div, .stMarkdown {
    color: #2a1e12 !important;
}

/* Streamlit form widgets */
.stTextInput > div > div > input,
.stTextArea > div > textarea,
.stSelectbox div[data-baseweb="select"],
.stRadio label,
.stSlider label {
    color: #2a1e12 !important;
    background-color: #fcfbf7 !important;
}

/* Radio and select option text */
.stRadio div[role="radiogroup"] label,
.stSelectbox div[role="option"] {
    color: #2a1e12 !important;
}

/* Sidebar adjustments */
[data-testid="stSidebar"] {
    background-color: #f1ede3 !important;
    color: #2a1e12 !important;
    border-right: 1px solid rgba(42, 30, 18, 0.08);
}

/* Metric and review cards */
.metric-card, .review-card {
    background: #fffdf8;
    border-radius: 12px;
    padding: 1rem;
    box-shadow: 0 2px 6px rgba(24, 18, 10, 0.08);
    margin-bottom: 0.75rem;
    color: #2a1e12;
}

/* Subtle accent for timestamps or muted text */
.review-card .timestamp,
.small-text,
.stCaption {
    color: #6c5f4b !important;
}

/* Buttons */
.stButton>button {
    border-radius: 6px;
}

button[kind="primary"] {
    background-color: #4c7f62 !important;
    color: #fdfcf7 !important;
}

button[kind="primary"]:hover {
    background-color: #3a5d48 !important;
    color: #fdfcf7 !important;
}

button[kind="secondary"] {
    background-color: #a7503c !important;
    color: #fdfcf7 !important;
}

button[kind="secondary"]:hover {
    background-color: #8d3f2d !important;
    color: #fdfcf7 !important;
}

/* Ensure Streamlit textareas show dark text */
textarea {
    color: #2a1e12 !important;
    background-color: #fcfbf7 !important;
}

.review-card {
    position: relative;
    transition: box-shadow 0.2s ease-in-out;
}

.review-card:hover {
    box-shadow: 0px 4px 12px rgba(24, 18, 10, 0.12);
}

.review-card.review-card-sound {
    background-color: #eef4ec;
}

.review-card.review-card-incorrect {
    background-color: #f5e8e6;
}

.review-card .reviewed-badge {
    position: absolute;
    top: 12px;
    right: 12px;
    background-color: #c19a20;
    color: #fdfcf7;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 0.8rem;
}

</style>
"""

RESPONSE_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "the-christian-project/pastoral-review")


def apply_portal_theme(page_title: str) -> None:
    """Apply the shared page configuration and background styling."""
    st.set_page_config(page_title=page_title, page_icon=None, layout="wide")
    st.markdown(BACKGROUND_STYLE, unsafe_allow_html=True)


def require_reviewer_auth() -> None:
    """Password gate for reviewer-facing dashboards."""
    secret = st.secrets.get("REVIEW_DASHBOARD_PASS") or os.getenv("DASHBOARD_PASSCODE")
    if not secret:
        st.error(
            "Reviewer password not configured. Set REVIEW_DASHBOARD_PASS (or DASHBOARD_PASSCODE) in your environment."
        )
        st.stop()

    if st.session_state.get("review_dashboard_authenticated"):
        return

    st.title("Pastoral Review Dashboard")
    st.caption("Authorized reviewers only.")
    password = st.text_input("Enter dashboard password:", type="password")
    if st.button("Unlock dashboard"):
        if password == secret:
            st.session_state["review_dashboard_authenticated"] = True
            st.experimental_rerun()
        else:
            st.error("Incorrect password. Please try again.")
    st.stop()


def normalize_email(value: str) -> str:
    return value.strip().lower()


def get_authorized_reviewer_set() -> Optional[Set[str]]:
    """Return the first-party authorized reviewer list, if configured."""
    raw = st.secrets.get("AUTHORIZED_REVIEWERS") or os.getenv("AUTHORIZED_REVIEWERS")
    if not raw:
        return None

    normalized: Set[str] = set()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            normalized = {normalize_email(item) for item in parsed if isinstance(item, str)}
        elif isinstance(parsed, str):
            normalized = {normalize_email(parsed)}
    except json.JSONDecodeError:
        normalized = {normalize_email(item) for item in raw.split(",")}

    normalized = {item for item in normalized if item}
    return normalized or None


def compute_response_id(question: str, timestamp: Optional[str], answer: str) -> str:
    base = f"{question.strip()}|{timestamp or ''}|{answer.strip()[:200]}"
    return str(uuid.uuid5(RESPONSE_NAMESPACE, base))
