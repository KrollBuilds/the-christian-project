"""Streamlit dashboard for pastoral review of AI responses."""

from __future__ import annotations

# TODO: integrate Firebase Auth for user accounts
# TODO: move logs to encrypted storage (e.g., Supabase or Firestore)
# TODO: implement admin metrics dashboard for usage and cost

from pathlib import Path
import sys

# Ensure the project root is on the Python path so package imports resolve.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, DefaultDict, Dict, List, Optional

from dotenv import load_dotenv
import streamlit as st

from app.auth_utils import get_current_user
from app.privacy_utils import sanitize_text
from app.reviewer_portal_utils import (
    apply_portal_theme,
    compute_response_id,
    get_authorized_reviewer_set,
    normalize_email,
    require_reviewer_auth,
)


from config import SETTINGS

load_dotenv()

DATA_PATHS = [
    Path("data/feedback"),
    Path("data/metrics"),
    Path("data/processed/vector_store"),
    Path("logs"),
]
for path in DATA_PATHS:
    path.mkdir(parents=True, exist_ok=True)

DATA_DIR = Path("data") / "feedback"
FEEDBACK_PATH = DATA_DIR / "feedback_log.json"
METRICS_DIR = Path("data") / "metrics"
REVIEW_LOG_PATH = METRICS_DIR / "pastor_feedback.jsonl"
CONV_LOG_PATH = Path("logs") / "generation_log.jsonl"

apply_portal_theme("Pastoral Review Dashboard")
require_reviewer_auth()


def load_feedback_entries() -> List[Dict[str, Any]]:
    entries: List[Dict[str, Any]] = []

    if FEEDBACK_PATH.exists():
        try:
            with FEEDBACK_PATH.open("r", encoding="utf-8") as file:
                entries.extend(json.load(file))
        except json.JSONDecodeError:
            st.warning("Unable to parse feedback_log.json; skipping.")

    if CONV_LOG_PATH.exists():
        with CONV_LOG_PATH.open("r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                    entries.append(entry)
                except json.JSONDecodeError:
                    continue

    normalized: List[Dict[str, Any]] = []
    for entry in entries:
        question = entry.get("question") or entry.get("prompt")
        answer = entry.get("answer") or entry.get("response")
        timestamp = entry.get("timestamp") or entry.get("datetime")
        tone_score = entry.get("tone_score")
        topic_cluster = entry.get("topic_cluster") or entry.get("topic") or "General Theology"
        response_id = (
            entry.get("response_id")
            or entry.get("id")
            or compute_response_id(question or "", timestamp, answer or "")
        )
        if not question or not answer:
            continue
        normalized.append(
            {
                "response_id": response_id,
                "question": question,
                "answer": answer,
                "timestamp": timestamp,
                "tone_score": tone_score,
                "topic_cluster": topic_cluster,
            }
        )
    normalized.sort(
        key=lambda e: e.get("timestamp") or "", reverse=True
    )
    return normalized


def load_existing_reviews() -> List[Dict[str, Any]]:
    if not REVIEW_LOG_PATH.exists():
        return []
    reviews: List[Dict[str, Any]] = []
    with REVIEW_LOG_PATH.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                reviews.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return reviews


def persist_review_entry(log_entry: Dict[str, Any]) -> None:
    sanitized_entry = {
        "response_id": log_entry.get("response_id"),
        "review_status": sanitize_text(log_entry.get("review_status")),
        "pastor_score": log_entry.get("pastor_score"),
        "pastor_notes": sanitize_text(log_entry.get("pastor_notes")) if log_entry.get("pastor_notes") else None,
        "reviewer_id": sanitize_text(log_entry.get("reviewer_id")),
        "reviewer_name": sanitize_text(log_entry.get("reviewer_name")),
        "timestamp": log_entry.get("timestamp"),
        "response_metadata": {
            "question": sanitize_text(log_entry.get("question")),
            "answer": sanitize_text(log_entry.get("answer")),
            "topic_cluster": sanitize_text(log_entry.get("topic_cluster")),
            "submitted": sanitize_text(log_entry.get("submitted")),
        },
        "user_id": get_current_user(),
    }

    existing_lines: List[str] = []
    if REVIEW_LOG_PATH.exists():
        with REVIEW_LOG_PATH.open("r", encoding="utf-8") as infile:
            for line in infile:
                stripped = line.strip()
                if not stripped:
                    continue
                try:
                    record = json.loads(stripped)
                except json.JSONDecodeError:
                    continue
                if (
                    record.get("response_id") == sanitized_entry["response_id"]
                    and record.get("reviewer_id") == sanitized_entry["reviewer_id"]
                ):
                    # Skip existing record for this reviewer/response combination (upsert behavior)
                    continue
                existing_lines.append(json.dumps(record, ensure_ascii=True))

    existing_lines.append(json.dumps(sanitized_entry, ensure_ascii=True))
    METRICS_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_LOG_PATH.open("w", encoding="utf-8") as outfile:
        outfile.write("\n".join(existing_lines) + "\n")


def display_metrics(reviews: List[Dict[str, Any]], entries: List[Dict[str, Any]]) -> None:
    reviewed_count = len(reviews)
    approved_count = sum(1 for review in reviews if review.get("review_status") == "approved")
    flagged_count = sum(1 for review in reviews if review.get("review_status") == "flagged")
    distinct_reviewers = {review.get("reviewer_id") for review in reviews if review.get("reviewer_id")}
    available_responses = {entry.get("response_id") for entry in entries if entry.get("response_id")}
    reviewed_responses = {review.get("response_id") for review in reviews if review.get("response_id")}
    pending_responses = len(available_responses - reviewed_responses)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Total Reviews Logged", reviewed_count)
    with col2:
        st.metric("Approved Responses", approved_count)
    with col3:
        st.metric("Flagged Responses", flagged_count)

    st.caption(
        f"Active reviewers: {len(distinct_reviewers)} | Responses pending review: {pending_responses}"
    )


def filter_entries(
    entries: List[Dict[str, Any]],
    review_index: DefaultDict[str, List[Dict[str, Any]]],
    reviewer_id: str,
) -> List[Dict[str, Any]]:
    st.sidebar.subheader("Filters")

    date_range = st.sidebar.date_input("Submitted date range", [])
    tone_min = st.sidebar.slider("Minimum tone score", 0.0, 1.0, 0.0, 0.05)
    search_term = st.sidebar.text_input("Search question or answer")
    show_pending_only = st.sidebar.checkbox("Only show items I have not reviewed", value=True)

    def is_in_date_range(timestamp: Optional[str]) -> bool:
        if not date_range:
            return True
        if not timestamp:
            return False
        try:
            dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        except ValueError:
            return False
        if len(date_range) == 1:
            start = datetime.combine(date_range[0], datetime.min.time())
            end = datetime.combine(date_range[0], datetime.max.time())
        else:
            start = datetime.combine(date_range[0], datetime.min.time())
            end = datetime.combine(date_range[-1], datetime.max.time())
        return start <= dt <= end

    filtered: List[Dict[str, Any]] = []
    for entry in entries:
        tone_score = entry.get("tone_score")
        question = entry.get("question", "")
        answer = entry.get("answer", "")
        timestamp = entry.get("timestamp")
        response_id = entry.get("response_id")

        if tone_score is not None and tone_score < tone_min:
            continue
        if search_term and search_term.lower() not in (question + " " + answer).lower():
            continue
        if not is_in_date_range(timestamp):
            continue
        if show_pending_only:
            reviewer_reviews = [
                review for review in review_index.get(response_id, []) if review.get("reviewer_id") == reviewer_id
            ]
            if reviewer_reviews:
                continue

        filtered.append(entry)
    return filtered


def build_review_index(
    reviews: List[Dict[str, Any]]
) -> DefaultDict[str, List[Dict[str, Any]]]:
    index: DefaultDict[str, List[Dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        response_id = review.get("response_id")
        if response_id:
            index[response_id].append(review)
    return index


def review_card(
    entry: Dict[str, Any],
    reviewer_id: str,
    reviewer_name: str,
    review_index: DefaultDict[str, List[Dict[str, Any]]],
) -> None:
    question = entry.get("question", "").strip()
    answer = entry.get("answer", "").strip()
    timestamp = entry.get("timestamp")
    tone_score = entry.get("tone_score")
    topic_cluster = entry.get("topic_cluster")
    response_id = entry.get("response_id")
    readable_time = timestamp or "Unknown timestamp"

    existing_reviews = review_index.get(response_id, [])
    reviewer_review = next(
        (item for item in existing_reviews if item.get("reviewer_id") == reviewer_id),
        None,
    )
    card_classes = ["review-card"]
    if reviewer_review:
        if reviewer_review.get("review_status") == "approved":
            card_classes.append("review-card-sound")
        elif reviewer_review.get("review_status") == "flagged":
            card_classes.append("review-card-incorrect")

    with st.container(border=True):
        st.markdown(f'<div class="{" ".join(card_classes)}">', unsafe_allow_html=True)
        if existing_reviews:
            st.markdown(
                '<span class="reviewed-badge">Reviewed</span>',
                unsafe_allow_html=True,
            )

        st.subheader(f"Question: {question}")
        st.markdown(f"**AI Response:** {answer}")
        metadata_text = f"Topic Cluster: {topic_cluster}"
        if tone_score is not None:
            metadata_text += f" | Tone Score: {tone_score:.2f}"
        metadata_text += f" | Submitted: {readable_time}"
        st.caption(metadata_text)

        expander_label = "Add Theological Notes"
        default_notes = reviewer_review.get("pastor_notes") if reviewer_review else ""
        with st.expander(expander_label, expanded=bool(default_notes)):
            notes_key = f"notes_{response_id}"
            pastor_notes = st.text_area(
                "Notes or Scriptural reference",
                value=default_notes or "",
                key=notes_key,
            )

        def submit_review(status: str, score: int) -> None:
            log_entry = {
                "response_id": response_id,
                "review_status": status,
                "pastor_score": score,
                "pastor_notes": pastor_notes.strip() or None,
                "reviewer_id": reviewer_id,
                "reviewer_name": reviewer_name,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "question": question,
                "answer": answer,
                "topic_cluster": topic_cluster,
                "submitted": readable_time,
            }
            try:
                persist_review_entry(log_entry)
            except OSError as exc:
                st.error(f"Unable to record the review: {exc}")
                return
            st.session_state["review_saved"] = {
                "response_id": response_id,
                "status": status,
            }
            st.experimental_rerun()

        disable_actions = reviewer_id == "" or reviewer_name == ""
        col1, col2 = st.columns([1, 1])
        with col1:
            st.button(
                "Approve",
                key=f"approve_{response_id}",
                help="Mark this response as doctrinally sound.",
                on_click=lambda: submit_review("approved", 1),
                type="primary",
                disabled=disable_actions,
            )
        with col2:
            st.button(
                "Flag for Revision",
                key=f"flag_{response_id}",
                help="Request doctrinal or pastoral revisions.",
                on_click=lambda: submit_review("flagged", -1),
                type="secondary",
                disabled=disable_actions,
            )

        if existing_reviews:
            st.markdown("---")
            st.markdown("**Recorded Reviews**")
            for review in existing_reviews:
                reviewer_label = review.get("reviewer_name") or review.get("reviewer_id") or "Unknown Reviewer"
                status_label = review.get("review_status", "unknown").capitalize()
                review_time = review.get("timestamp", "Unknown timestamp")
                notes = review.get("pastor_notes")
                st.caption(f"{reviewer_label} • {status_label} • {review_time}")
                if notes:
                    st.markdown(f"> {notes}")
        st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    st.title("Pastoral Review Dashboard")
    st.caption("Evaluate AI-generated responses, document doctrinal findings, and maintain an auditable record.")

    authorized_reviewers = get_authorized_reviewer_set()

    with st.sidebar:
        st.title("Reviewer Panel")
        st.markdown("### Navigation")
        st.page_link("review_dashboard.py", label="Pending Reviews")
        st.page_link("review_history.py", label="My Review History")
        st.page_link("metrics_overview.py", label="Feedback Metrics")

        st.markdown("### Reviewer Details")
        reviewer_email_input = st.text_input("Reviewer email")
        reviewer_name_input = st.text_input("Display name")

    reviewer_email = normalize_email(reviewer_email_input) if reviewer_email_input else ""
    reviewer_name = reviewer_name_input.strip()

    if authorized_reviewers is not None:
        if not reviewer_email:
            st.info("Enter an authorized reviewer email to begin.")
            return
        if reviewer_email not in authorized_reviewers:
            st.error("This reviewer email is not authorized. Contact the administrator to request access.")
            return

    if not reviewer_email:
        st.info("Enter your reviewer email to begin.")
        return

    if not reviewer_name:
        st.info("Provide your display name so your reviews can be attributed.")
        return

    saved_state = st.session_state.pop("review_saved", None)
    if saved_state:
        status = saved_state.get("status")
        if status == "approved":
            st.success("Review recorded as approved.")
        elif status == "flagged":
            st.warning("Review recorded as flagged for revision.")

    entries = load_feedback_entries()
    reviews = load_existing_reviews()
    review_index = build_review_index(reviews)

    with st.expander("Review Activity Summary", expanded=True):
        display_metrics(reviews, entries)

    filtered_entries = filter_entries(entries, review_index, reviewer_email)

    def show_privacy_caption() -> None:
        if SETTINGS.get("privacy_disclaimer", True):
            st.caption(
                "Please refrain from sharing personal or identifying details. Conversations are logged anonymously for quality improvement."
            )

    if not filtered_entries:
        st.info("No entries available with the current filters.")
        show_privacy_caption()
        return

    for entry in filtered_entries:
        review_card(entry, reviewer_email, reviewer_name, review_index)

    show_privacy_caption()


if __name__ == "__main__":
    main()
