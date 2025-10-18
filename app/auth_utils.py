"""Authentication utilities (future Firebase/Supabase integration)."""

from __future__ import annotations

import streamlit as st


def get_current_user() -> str:
    """Return mock user ID until full auth is added."""
    return st.session_state.get("user_id", "guest")


def login_button() -> None:
    st.info("🔒 Sign-in required for saved chat history (coming soon).")


def require_login() -> None:
    if "user_id" not in st.session_state:
        login_button()
        st.stop()
