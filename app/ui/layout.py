"""Layout helpers that organize the Streamlit shell."""

from __future__ import annotations

from pathlib import Path
from typing import Callable

import streamlit as st

from app.app_config.theme import apply_theme_to_dom, ensure_theme


_CSS_PATH = Path(__file__).with_name("layout.css")


def _read_css() -> str:
    return _CSS_PATH.read_text(encoding="utf-8")


def configure_page() -> None:
    """Set global page metadata and inject theme styles."""
    st.set_page_config(
        page_title="The Christian Project — MVP Preview",
        page_icon="✝️",
        layout="wide",
        initial_sidebar_state="expanded",
    )
    ensure_theme()
    st.markdown(f"<style>{_read_css()}</style>", unsafe_allow_html=True)
    apply_theme_to_dom()


def render_shell(sidebar_renderer: Callable[[], None], main_renderer: Callable[[], None]) -> None:
    """Render the top-level banner, shell columns, and footer."""
    configure_page()

    st.markdown(
        """
        <div class="tcp-banner" role="banner">
            Prototype — The Christian Project (MVP Preview)
        </div>
        """,
        unsafe_allow_html=True,
    )

    columns = st.columns([1, 3], gap="medium")
    with columns[0]:
        st.markdown("<nav class='tcp-sidebar' aria-label='Primary navigation'>", unsafe_allow_html=True)
        sidebar_renderer()
        st.markdown("</nav>", unsafe_allow_html=True)

    with columns[1]:
        st.markdown("<section class='tcp-main' role='main'>", unsafe_allow_html=True)
        main_renderer()
        st.markdown("</section>", unsafe_allow_html=True)

    st.markdown(
        """
        <footer class="tcp-footer" role="contentinfo">
            For personal or spiritual matters, please speak with your pastor.
        </footer>
        """,
        unsafe_allow_html=True,
    )


__all__ = ["configure_page", "render_shell"]
