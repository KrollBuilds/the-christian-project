"""Streamlit dashboard for pastoral reviewers to inspect queued AI responses."""

from __future__ import annotations

import os
from typing import Any, Dict, List

import requests
import streamlit as st

DEFAULT_FETCH_URL = (
    "https://the-christian-review-dashboard-production.up.railway.app/api/get_pending_reviews"
)
REVIEW_QUEUE_ENDPOINT = os.getenv("REVIEW_QUEUE_ENDPOINT", DEFAULT_FETCH_URL)
REVIEW_API_KEY = os.getenv("REVIEW_API_KEY")
REVIEW_API_TIMEOUT = os.getenv("REVIEW_API_TIMEOUT", "5")

st.set_page_config(page_title="The Christian Project — Review Queue", page_icon="🕊️")
st.title("Pastoral Review Queue")
st.caption("Review each AI-generated response before it is marked as fully published.")


def fetch_pending_reviews() -> List[Dict[str, Any]]:
    headers: Dict[str, str] = {}
    if REVIEW_API_KEY:
        headers["Authorization"] = f"Bearer {REVIEW_API_KEY}"
    try:
        timeout = float(REVIEW_API_TIMEOUT)
    except (TypeError, ValueError):
        timeout = 5.0

    response = requests.get(
        REVIEW_QUEUE_ENDPOINT,
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if isinstance(payload, list):
        return payload
    st.warning("Unexpected payload from review API.")
    return []


def render_queue(items: List[Dict[str, Any]]) -> None:
    if not items:
        st.info("No pending responses for review.")
        return

    for idx, item in enumerate(items, start=1):
        st.subheader(f"Submission {idx}")
        st.write(f"**Question:** {item.get('question', 'N/A')}")
        st.write(f"**AI Response:** {item.get('answer', 'N/A')}")
        st.write(f"**Tone Score:** {item.get('tone_score', 'N/A')}")
        st.write(f"**Submitted By:** {item.get('submitted_by', 'Unknown')}")
        st.write(f"**Timestamp:** {item.get('timestamp', 'N/A')}")
        col1, col2 = st.columns(2)
        with col1:
            st.button("Approve", key=f"approve_{idx}")
        with col2:
            st.button("Flag for Revision", key=f"flag_{idx}")
        st.divider()


try:
    queue_items = fetch_pending_reviews()
    render_queue(queue_items)
except Exception as exc:
    st.warning(f"Unable to load review queue: {exc}")
