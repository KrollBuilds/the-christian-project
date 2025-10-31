"""App-level configuration helpers."""

from .theme import (
    apply_theme_to_dom,
    current_theme,
    ensure_theme,
    set_theme,
    sync_toggle_state,
    toggle_theme,
)

__all__ = [
    "apply_theme_to_dom",
    "current_theme",
    "ensure_theme",
    "set_theme",
    "sync_toggle_state",
    "toggle_theme",
]
