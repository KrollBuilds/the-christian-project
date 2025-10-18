"""Streamlit dashboard for pastoral review of AI responses."""

from __future__ import annotations

import csv
import json
import os
from collections import defaultdict
from datetime import datetime
from io import StringIO
from pathlib import Path
from typing import Any, DefaultDict, Dict, List, Optional, Tuple

import streamlit as st

DATA_DIR = Path("data") / "feedback"
FEEDBACK_PATH = DATA_DIR / "feedback_log.json"
REVIEW_LOG_PATH = DATA_DIR / "review_log.jsonl"
CONV_LOG_PATH = Path("logs") / "generation_log.jsonl"

st.set_page_config(
    page_title="Pastoral Review Dashboard",
    page_icon="📖",
    layout="wide",
)

BACKGROUND_STYLE = """
<style>
body, .stApp {
    background-color: #f7f4e9;
    color: #222222;                    /* darker default text */
    font-family: "Helvetica Neue", Helvetica, Arial, sans-serif;
}

/* Headings and markdown text */
h1, h2, h3, h4, h5, h6, p, label, span, div, .stMarkdown {
    color: #222222 !important;
}

/* Streamlit form widgets */
.stTextInput > div > div > input,
.stTextArea > div > textarea,
.stSelectbox div[data-baseweb="select"],
.stRadio label,
.stSlider label {
    color: #222222 !important;
    background-color: #fffef8 !important;
}

/* Radio and select option text */
.stRadio div[role="radiogroup"] label,
.stSelectbox div[role="option"] {
    color: #222222 !important;
}

/* Sidebar adjustments */
[data-testid="stSidebar"] {
    background-color: #f7f4e9 !important;
    color: #222222 !important;
}

/* Metric and review cards */
.metric-card, .review-card {
    background: #ffffff;
    border-radius: 12px;
    padding: 1rem;
    box-shadow: 0 2px 8px rgba(0,0,0,0.08);
    margin-bottom: 0.75rem;
    color: #222222;
}

/* Subtle accent for timestamps or muted text */
.review-card .timestamp,
.small-text,
.stCaption {
    color: #555555 !important;
}

/* Buttons */
button[kind="primary"], .stButton>button {
    background-color: #d4af37 !important;
    color: #ffffff !important;
    border-radius: 6px;
}
button[kind="secondary"], .stButton>button:hover {
    background-color: #c29b30 !important;
    color: #ffffff !important;
}

/* Ensure Streamlit textareas show dark text */
textarea {
    color: #222222 !important;
    background-color: #fffef8 !important;
}

.review-card {
    position: relative;
    transition: box-shadow 0.2s ease-in-out;
}

.review-card:hover {
    box-shadow: 0px 4px 12px rgba(0,0,0,0.12);
}

.review-card.review-card-sound {
    background-color: #eaf7ea;
}

.review-card.review-card-incorrect {
    background-color: #fdecea;
}

.review-card .reviewed-badge {
    position: absolute;
    top: 12px;
    right: 12px;
    background-color: #d4af37;
    color: #ffffff;
    padding: 3px 8px;
    border-radius: 6px;
    font-size: 0.8rem;
}

</style>
"""


st.markdown(BACKGROUND_STYLE, unsafe_allow_html=True)


def authenticate() -> bool:
    expected = os.environ.get("DASHBOARD_PASSCODE")
    if not expected:
        st.error("🔒 This dashboard is restricted to pastoral reviewers.")
        return False

    st.sidebar.header("Access")
    entered = st.sidebar.text_input("Enter Passcode", type="password")
    if not entered:
        st.info("Enter the pastoral passcode to continue.")
        return False

    if entered != expected:
        st.error("Incorrect passcode.")
        return False

    return True


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
        if not question or not answer:
            continue
        normalized.append(
            {
                "question": question,
                "answer": answer,
                "timestamp": timestamp,
                "tone_score": tone_score,
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


def record_review(review: Dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with REVIEW_LOG_PATH.open("a", encoding="utf-8") as file:
        file.write(json.dumps(review, ensure_ascii=True) + "\n")


def delete_review_entry(question: str, answer: str, reviewer: str) -> bool:
    if not REVIEW_LOG_PATH.exists():
        return False

    remaining_lines: List[str] = []
    removed = False

    with REVIEW_LOG_PATH.open("r", encoding="utf-8") as source:
        for line in source:
            stripped = line.strip()
            if not stripped:
                continue
            try:
                entry = json.loads(stripped)
            except json.JSONDecodeError:
                remaining_lines.append(stripped)
                continue

            matches_question = entry.get("question") == question
            matches_answer = entry.get("answer") == answer
            matches_reviewer = entry.get("reviewer") == reviewer

            if matches_question and matches_answer and matches_reviewer:
                removed = True
                continue

            remaining_lines.append(json.dumps(entry, ensure_ascii=True))

    if removed:
        with REVIEW_LOG_PATH.open("w", encoding="utf-8") as destination:
            for line in remaining_lines:
                destination.write(line + "\n")
    return removed


def display_metrics(reviews: List[Dict[str, Any]], entries: List[Dict[str, Any]]) -> None:
    reviewed_count = len(reviews)
    sound_count = sum(1 for review in reviews if review.get("accuracy") == "Sound")

    tone_scores = [entry.get("tone_score") for entry in entries if entry.get("tone_score") is not None]
    avg_tone = sum(tone_scores) / len(tone_scores) if tone_scores else None

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("Responses Reviewed", reviewed_count)
    with col2:
        sound_pct = (sound_count / reviewed_count * 100) if reviewed_count else 0
        st.metric("Doctrinally Sound", f"{sound_pct:.0f}%")
    with col3:
        tone_display = f"{avg_tone:.2f}" if avg_tone is not None else "—"
        st.metric("Average Tone Score", tone_display)


def filter_entries(
    entries: List[Dict[str, Any]],
    review_index: DefaultDict[Tuple[str, str], List[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    st.sidebar.header("Filters")

    date_range = st.sidebar.date_input("Date range", [])
    tone_min = st.sidebar.slider("Tone score ≥", 0.0, 1.0, 0.0, 0.05)
    search_term = st.sidebar.text_input("Search question text")
    show_unrated = st.sidebar.checkbox("Show only unrated", value=False)
    show_reviewed_only = st.sidebar.checkbox("Show only reviewed entries", value=False)

    reviewed_keys = set(review_index.keys())

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
        timestamp = entry.get("timestamp")
        key = (entry.get("question"), entry.get("answer"))

        if tone_score is not None and tone_score < tone_min:
            continue
        if search_term and search_term.lower() not in question.lower():
            continue
        if not is_in_date_range(timestamp):
            continue
        if show_unrated and key in reviewed_keys:
            continue
        if show_reviewed_only and key not in reviewed_keys:
            continue

        filtered.append(entry)
    return filtered


def build_review_index(
    reviews: List[Dict[str, Any]]
) -> DefaultDict[Tuple[str, str], List[Dict[str, Any]]]:
    index: DefaultDict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for review in reviews:
        question = review.get("question")
        answer = review.get("answer")
        if question and answer:
            index[(question, answer)].append(review)
    return index


def generate_review_csv(reviews: List[Dict[str, Any]]) -> bytes:
    fieldnames = [
        "question",
        "answer",
        "accuracy",
        "tone",
        "completeness",
        "reviewer",
        "timestamp",
    ]
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for review in reviews:
        writer.writerow({field: review.get(field, "") or "" for field in fieldnames})
    return buffer.getvalue().encode("utf-8")


def review_card(
    entry: Dict[str, Any],
    reviewer_name: str,
    review_index: DefaultDict[Tuple[str, str], List[Dict[str, Any]]],
) -> None:
    question = entry.get("question", "")
    answer = entry.get("answer", "")
    timestamp = entry.get("timestamp")
    tone_score = entry.get("tone_score")
    readable_time = timestamp or "Unknown timestamp"
    key = (question, answer)

    existing_reviews = review_index.get(key, [])
    reviewer_review = next(
        (item for item in existing_reviews if item.get("reviewer") == reviewer_name),
        None,
    )
    highlight_review = reviewer_review or (existing_reviews[0] if existing_reviews else None)

    card_classes = ["review-card"]
    if highlight_review:
        accuracy_value = highlight_review.get("accuracy")
        if accuracy_value == "Sound":
            card_classes.append("review-card-sound")
        elif accuracy_value == "Incorrect":
            card_classes.append("review-card-incorrect")

    with st.container():
        st.markdown(
            f'<div class="{" ".join(card_classes)}">', unsafe_allow_html=True
        )
        if existing_reviews:
            st.markdown(
                '<span class="reviewed-badge">✅ Reviewed</span>',
                unsafe_allow_html=True,
            )

        if reviewer_review:
            delete_state_key = f"delete_confirm_{hash((question, answer, reviewer_name))}"
            if st.button(
                "🗑️ Remove Review",
                key=f"remove_{hash((question, answer, reviewer_name))}",
            ):
                st.session_state[delete_state_key] = True
            if st.session_state.get(delete_state_key):
                st.warning("This will permanently remove your review.")
                if st.button(
                    "Confirm Delete",
                    key=f"confirm_delete_{hash((question, answer, reviewer_name))}",
                ):
                    try:
                        removed = delete_review_entry(question, answer, reviewer_name)
                    except OSError as exc:
                        st.error(f"Failed to delete review: {exc}")
                    else:
                        if removed:
                            st.session_state["delete_success"] = True
                        else:
                            st.warning("No matching review found to delete.")
                        st.session_state.pop(delete_state_key, None)
                        st.experimental_rerun()

        st.markdown(f"### Question\n{question}")
        st.markdown(f"### Response\n{answer}")
        meta_parts = [f"🕓 {readable_time}"]
        if tone_score is not None:
            meta_parts.append(f"🎚️ Tone score: {tone_score}")
        st.markdown(" | ".join(meta_parts))

        accuracy_options = ["Sound", "Needs Review", "Incorrect"]
        tone_options = ["Pastoral", "Neutral", "Off-tone"]
        completeness_options = ["Complete", "Partial"]

        accuracy_index = (
            accuracy_options.index(reviewer_review.get("accuracy"))
            if reviewer_review and reviewer_review.get("accuracy") in accuracy_options
            else 0
        )
        tone_index = (
            tone_options.index(reviewer_review.get("tone"))
            if reviewer_review and reviewer_review.get("tone") in tone_options
            else 0
        )
        completeness_index = (
            completeness_options.index(reviewer_review.get("completeness"))
            if reviewer_review
            and reviewer_review.get("completeness") in completeness_options
            else 0
        )

        accuracy = st.radio(
            "Accuracy",
            options=accuracy_options,
            index=accuracy_index,
            format_func=lambda choice: {
                "Sound": "✅ Sound",
                "Needs Review": "⚠️ Needs Review",
                "Incorrect": "❌ Incorrect",
            }[choice],
            key=f"accuracy_{readable_time}_{question}",
        )
        tone = st.radio(
            "Tone",
            options=tone_options,
            index=tone_index,
            format_func=lambda choice: {
                "Pastoral": "🙏 Pastoral",
                "Neutral": "😐 Neutral",
                "Off-tone": "⚠️ Off-tone",
            }[choice],
            key=f"tone_{readable_time}_{question}",
        )
        completeness = st.radio(
            "Completeness",
            options=completeness_options,
            index=completeness_index,
            format_func=lambda choice: {
                "Complete": "📖 Complete",
                "Partial": "✂️ Partial",
            }[choice],
            key=f"completeness_{readable_time}_{question}",
        )

        comments = st.text_area(
            "Add reviewer notes (optional)",
            (reviewer_review.get("comments") or "") if reviewer_review else "",
            key=f"comments_{readable_time}_{question}",
        )

        if st.button("Save Review", key=f"save_{readable_time}_{question}"):
            review_entry = {
                "question": question,
                "answer": answer,
                "accuracy": accuracy,
                "tone": tone,
                "completeness": completeness,
                "comments": comments.strip() or None,
                "reviewer": reviewer_name,
                "timestamp": datetime.utcnow().isoformat(),
            }
            record_review(review_entry)
            st.session_state["save_success"] = True
            # TODO: Archive deleted reviews and sync live with the training dataset builder.
            st.experimental_rerun()
        st.markdown("</div>", unsafe_allow_html=True)


def main() -> None:
    if not authenticate():
        return

    st.title("📖 Pastoral Review Dashboard")
    st.caption("Evaluate responses for theological accuracy, clarity, and tone.")

    reviewer_name = st.sidebar.text_input("Reviewer name", "")
    if not reviewer_name:
        st.warning("Please enter your name to record reviews.")
        return

    if st.session_state.pop("save_success", False):
        st.success("✅ Review saved!")
    if st.session_state.pop("delete_success", False):
        st.success("Review deleted")

    entries = load_feedback_entries()
    reviews = load_existing_reviews()
    review_index = build_review_index(reviews)

    with st.expander("Summary", expanded=True):
        display_metrics(reviews, entries)
        if reviews:
            st.download_button(
                "⬇️ Download review summary",
                data=generate_review_csv(reviews),
                file_name="review_export.csv",
                mime="text/csv",
            )

    filtered_entries = filter_entries(entries, review_index)

    if not filtered_entries:
        st.info("No entries available with the current filters.")
        return

    for entry in filtered_entries:
        review_card(entry, reviewer_name, review_index)


if __name__ == "__main__":
    main()
