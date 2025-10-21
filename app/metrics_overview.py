"""Placeholder page for aggregate feedback metrics (Phase 2)."""

from __future__ import annotations

from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import streamlit as st

from app.reviewer_portal_utils import apply_portal_theme, require_reviewer_auth

apply_portal_theme("Feedback Metrics")
require_reviewer_auth()

with st.sidebar:
    st.title("Reviewer Panel")
    st.markdown("### Navigation")
    st.page_link("review_dashboard.py", label="Pending Reviews")
    st.page_link("review_history.py", label="My Review History")
    st.page_link("metrics_overview.py", label="Feedback Metrics")

st.title("Feedback Metrics Overview")
st.caption("Aggregate doctrinal insights and reviewer trends will be available here in Phase 2.")

st.info(
    "Future enhancements will surface charts for review volume, doctrinal risk categories, and reviewer contributions once authenticated accounts are live."
)
