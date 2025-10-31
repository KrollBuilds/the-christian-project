"""Custom UI widgets used across the Streamlit layout."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional
from uuid import uuid4

import streamlit as st
from streamlit.delta_generator import DeltaGenerator


@dataclass
class MessageMeta:
    """Metadata attached to a rendered message bubble."""

    role: str
    aria_label: Optional[str] = None
    pending: bool = False
    message_id: Optional[str] = None


def _role_label(role: str) -> str:
    if role == "assistant":
        return "The Christian Project"
    if role == "system":
        return "System"
    return "You"


def render_message_bubble(
    content: str, meta: MessageMeta, *, container: Optional[DeltaGenerator] = None
) -> DeltaGenerator:
    """Render a stylized message bubble while preserving markdown rendering."""
    label = meta.aria_label or f"{_role_label(meta.role)} message"
    message_id = meta.message_id or f"tcp-msg-{uuid4().hex}"
    classes = ["tcp-message", f"tcp-message--{meta.role}"]
    if meta.pending:
        classes.append("tcp-message--pending")

    target = container or st.container()
    target.markdown(
        f"""
        <article id="{message_id}" class="{' '.join(classes)}" role="article" aria-label="{label}" tabindex="0">
            <header class="tcp-message__header">
                <span class="tcp-message__role">{_role_label(meta.role)}</span>
            </header>
            <div class="tcp-message__body">
        """,
        unsafe_allow_html=True,
    )
    target.markdown(content)
    if meta.pending:
        render_typing_indicator(container=target)
    target.markdown(
        """
            </div>
        </article>
        """,
        unsafe_allow_html=True,
    )
    return target


def render_typing_indicator(
    *, label: str = "AI is typing…", container: Optional[DeltaGenerator] = None
) -> None:
    """Display a typing indicator animation."""
    target = container or st
    target.markdown(
        f"""
        <div class="tcp-typing" role="status" aria-live="polite" aria-label="{label}">
            <span class="tcp-typing__dot"></span>
            <span class="tcp-typing__dot"></span>
            <span class="tcp-typing__dot"></span>
            <span class="tcp-typing__label">{label}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def render_skeleton_message(
    *, label: str = "Preparing a faithful response…", container: Optional[DeltaGenerator] = None
) -> None:
    """Render a shimmering skeleton placeholder while waiting for content."""
    target = container or st
    target.markdown(
        f"""
        <div class="tcp-skeleton" role="status" aria-live="polite" aria-label="{label}">
            <div class="tcp-skeleton__line tcp-skeleton__line--wide"></div>
            <div class="tcp-skeleton__line tcp-skeleton__line--medium"></div>
            <div class="tcp-skeleton__line tcp-skeleton__line--narrow"></div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def accessible_button(
    label: str,
    *,
    key: str,
    aria_label: Optional[str] = None,
    icon: Optional[str] = None,
    help_text: Optional[str] = None,
) -> bool:
    """
    Render a Streamlit button with enforced accessibility attributes.

    Returns True when clicked.
    """
    text = f"{icon or ''} {label}".strip()
    wrapper = st.container()
    marker_id = f"tcp-btn-marker-{uuid4().hex}"
    wrapper.markdown(f"<div id=\"{marker_id}\" class=\"tcp-button-marker\"></div>", unsafe_allow_html=True)
    clicked = wrapper.button(text, key=key, use_container_width=True, help=help_text)

    aria = aria_label or label
    st.markdown(
        f"""
        <script>
        (function() {{
            const doc = window.parent?.document ?? document;
            if (!doc) {{
                return;
            }}
            const marker = doc.querySelector("#{marker_id}");
            if (!marker) {{
                return;
            }}
            const base = marker.closest('[data-testid="element-container"]');
            if (!base) {{
                return;
            }}
            const button = base.querySelector("button");
            if (!button) {{
                return;
            }}
            button.setAttribute("aria-label", "{aria}");
            button.setAttribute("tabindex", "0");
        }})();
        </script>
        """,
        unsafe_allow_html=True,
    )
    return clicked


__all__ = [
    "MessageMeta",
    "accessible_button",
    "render_message_bubble",
    "render_skeleton_message",
    "render_typing_indicator",
]
