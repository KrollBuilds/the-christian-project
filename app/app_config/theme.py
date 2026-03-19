"""Theme management helpers for the Streamlit UI."""

from __future__ import annotations

from typing import Literal, Optional

import streamlit as st

ThemeName = Literal["light", "dark"]

_THEME_KEY = "ui_theme"
_TOGGLE_SYNC_KEY = "ui_theme_toggle"
_DEFAULT_THEME: ThemeName = "dark"


def ensure_theme(default: ThemeName = _DEFAULT_THEME) -> ThemeName:
    """Initialize and return the current theme stored in session state."""
    if _THEME_KEY not in st.session_state:
        st.session_state[_THEME_KEY] = default
        st.session_state[_TOGGLE_SYNC_KEY] = default == "dark"
    elif _TOGGLE_SYNC_KEY not in st.session_state:
        st.session_state[_TOGGLE_SYNC_KEY] = st.session_state[_THEME_KEY] == "dark"
    return st.session_state[_THEME_KEY]  # type: ignore[return-value]


def current_theme() -> ThemeName:
    """Return the active theme, guaranteeing initialization."""
    return ensure_theme()


def set_theme(theme: ThemeName) -> None:
    """Persist the desired theme into session state."""
    st.session_state[_THEME_KEY] = theme
    st.session_state[_TOGGLE_SYNC_KEY] = theme == "dark"


def toggle_theme() -> ThemeName:
    """Flip between light and dark themes, returning the new value."""
    theme = current_theme()
    theme = "dark" if theme == "light" else "light"
    set_theme(theme)
    return theme


def sync_toggle_state(toggle_value: Optional[bool]) -> None:
    """Synchronize the toggle widget with the stored theme value."""
    if toggle_value is None:
        return
    desired = "dark" if toggle_value else "light"
    set_theme(desired)  # handles updating toggle state as well


def apply_theme_to_dom() -> None:
    """Inject a script to keep the HTML body in sync with the chosen theme."""
    theme = current_theme()
    st.markdown(
        f"""
        <script>
        (function() {{
            const targetTheme = "{theme}";
            const doc = window.parent?.document ?? document;
            if (!doc) {{
                return;
            }}
            const body = doc.body;
            const root = doc.documentElement;
            if (root) {{
                root.setAttribute("data-theme", targetTheme);
            }}
            if (body) {{
                body.setAttribute("data-theme", targetTheme);
            }}
        }})();
        </script>
        """,
        unsafe_allow_html=True,
    )


__all__ = [
    "apply_theme_to_dom",
    "current_theme",
    "ensure_theme",
    "set_theme",
    "sync_toggle_state",
    "toggle_theme",
]
