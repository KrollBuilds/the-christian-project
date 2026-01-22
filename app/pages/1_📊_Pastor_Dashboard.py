"""Pastor Dashboard for reviewing submitted questions."""

import streamlit as st
import json
import os
from pathlib import Path
from datetime import datetime
import pandas as pd
from typing import List, Dict, Any
import sys

# Add utils to path
sys.path.append(str(Path(__file__).parent.parent))
from utils.training_data import save_approved_question, update_review_queue_topic

# Predefined topic categories (used in filters and re-tagging)
PREDEFINED_TOPICS = [
    "General",
    "Holy Communion",
    "Devotion",
    "Bible Studies",
    "Family",
    "Prayer",
    "Trinity"
]

# Set page configuration
st.set_page_config(
    page_title="Pastor Dashboard",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Add mobile-responsive CSS
st.markdown("""
<style>
/* Mobile-First Responsive Styles for Pastor Dashboard */

/* Ensure proper font sizing on mobile */
@media (max-width: 768px) {
    /* Make metrics stack vertically */
    [data-testid="column"] {
        width: 100% !important;
        flex: 0 0 100% !important;
        min-width: 100% !important;
        margin-bottom: 1rem;
    }

    /* Full-width filters and inputs */
    .stSelectbox, .stTextInput, .stTextArea {
        width: 100% !important;
    }

    /* Improve touch targets for mobile */
    button {
        min-height: 44px;
        min-width: 44px;
        padding: 0.75rem 1rem;
        font-size: 16px;
    }

    /* Horizontal scroll for tables */
    .dataframe {
        overflow-x: auto;
        -webkit-overflow-scrolling: touch;
        display: block;
    }

    /* Improve expander readability */
    .streamlit-expanderHeader {
        font-size: 0.9rem;
        line-height: 1.4;
        padding: 0.75rem;
    }

    /* Text areas full width */
    textarea {
        width: 100% !important;
        max-width: 100% !important;
        font-size: 16px !important;
    }

    /* Stack columns inside expanders */
    .stExpander [data-testid="column"] {
        width: 100% !important;
        flex: 0 0 100% !important;
    }

    /* Better spacing for mobile */
    .stMarkdown h1 {
        font-size: 1.5rem;
    }

    .stMarkdown h2 {
        font-size: 1.25rem;
    }

    .stMarkdown h3 {
        font-size: 1.1rem;
    }

    /* Metrics cards */
    [data-testid="metric-container"] {
        padding: 1rem;
    }
}

/* Tablet breakpoint */
@media (min-width: 769px) and (max-width: 1024px) {
    [data-testid="column"] {
        flex: 0 0 50% !important;
        width: 50% !important;
    }
}

/* Better focus states for accessibility */
button:focus-visible,
input:focus-visible,
textarea:focus-visible,
select:focus-visible {
    outline: 2px solid #1e3a8a;
    outline-offset: 2px;
}
</style>
""", unsafe_allow_html=True)

# Initialize authentication state
if "pastor_authenticated" not in st.session_state:
    st.session_state.pastor_authenticated = False

# Authentication gate
def check_authentication():
    """Verify pastor credentials before showing dashboard."""
    if st.session_state.pastor_authenticated:
        return True

    st.title("Pastor Access Only")
    st.markdown("This dashboard is restricted to authorized pastoral staff.")

    # Password input
    password = st.text_input(
        "Enter dashboard password:",
        type="password",
        key="pastor_password_input",
        help="Contact the administrator if you don't have access"
    )

    col1, col2 = st.columns([1, 4])
    with col1:
        if st.button("Login", type="primary", use_container_width=True):
            correct_password = os.getenv("PASTOR_PASSWORD")

            if not correct_password:
                st.error(
                    "⚠️ Dashboard authentication is not configured. "
                    "Please contact your system administrator."
                )
                st.stop()

            if password == correct_password:
                st.session_state.pastor_authenticated = True
                st.success("Authentication successful!")
                st.rerun()
            else:
                # Track failed login attempts for rate limiting
                if "failed_login_attempts" not in st.session_state:
                    st.session_state.failed_login_attempts = 0

                st.session_state.failed_login_attempts += 1

                if st.session_state.failed_login_attempts >= 5:
                    st.error("⚠️ Too many failed attempts. Please try again later.")
                    st.stop()

                st.error("Incorrect password. Please try again.")

    return False

# Exit if not authenticated
if not check_authentication():
    st.stop()

# ============================================================================
# AUTHENTICATED DASHBOARD CONTENT BELOW
# ============================================================================

# Header with logout
col1, col2 = st.columns([4, 1])
with col1:
    st.title("Pastor Dashboard - Question Review")
    st.markdown("Review and manage questions submitted through The Christian Project")
with col2:
    st.write("")  # Spacing
    if st.button("Logout", use_container_width=True):
        st.session_state.pastor_authenticated = False
        st.rerun()

# Load questions from JSONL file
def load_questions() -> List[Dict[str, Any]]:
    """Load all questions from review queue with comprehensive error handling."""
    # Use absolute path from project root
    project_root = Path(__file__).parent.parent.parent
    questions_file = project_root / "data" / "metrics" / "review_queue.jsonl"

    if not questions_file.exists():
        st.info(
            "📭 No questions have been submitted yet.\n\n"
            "Questions will appear here after users interact with the chat interface."
        )
        return []

    questions = []
    parse_errors = 0

    try:
        with questions_file.open("r", encoding="utf-8") as f:
            for line_num, line in enumerate(f, 1):
                line = line.strip()
                if line:
                    try:
                        questions.append(json.loads(line))
                    except json.JSONDecodeError as e:
                        parse_errors += 1
                        import logging
                        # Log the error with the problematic content for debugging
                        logging.warning(
                            f"Skipping malformed JSON on line {line_num}: {e}\n"
                            f"Content preview: {line[:200]}"
                        )
                        # Also save to a separate error log for investigation
                        error_log = questions_file.parent / "malformed_entries.log"
                        with error_log.open("a", encoding="utf-8") as ef:
                            from datetime import datetime
                            ef.write(
                                f"\n{'='*60}\n"
                                f"Time: {datetime.now().isoformat()}\n"
                                f"Line: {line_num}\n"
                                f"Error: {e}\n"
                                f"Content: {line}\n"
                            )

    except PermissionError:
        st.error(
            "🔒 Permission denied when accessing question database.\n\n"
            "Please ensure the application has read permissions for:\n"
            f"`{questions_file}`"
        )
        return []

    except Exception as e:
        st.error(
            "⚠️ Unexpected error loading questions.\n\n"
            f"**Error type:** {type(e).__name__}\n"
            f"**Error message:** {str(e)}\n\n"
            "Please contact your system administrator."
        )
        import logging
        import traceback
        logging.exception("Failed to load questions")

        # Show detailed error in expander for debugging
        with st.expander("🔍 Technical Details"):
            st.code(traceback.format_exc(), language="python")

        return []

    if parse_errors > 0:
        st.warning(
            f"⚠️ {parse_errors} malformed entries were skipped. "
            "Showing only valid questions."
        )

    return questions

# Load data
questions = load_questions()

# Show warning if no data
if not questions:
    st.warning("No questions have been submitted yet.")
    st.info("Questions will appear here after users interact with the chat interface.")
    st.stop()

# ============================================================================
# DASHBOARD OVERVIEW METRICS
# ============================================================================

st.header("Overview")

# Calculate metrics
total_questions = len(questions)
# Normalize topics to proper case for counting
unique_topics = len(set(q.get("topic_cluster", "General").title() for q in questions))
avg_tone = sum(q.get("tone_score", 0.5) for q in questions) / total_questions if total_questions > 0 else 0

# Recent questions (last 7 days)
from datetime import datetime, timedelta
now = datetime.now()
recent_cutoff = now - timedelta(days=7)

recent_count = 0
for q in questions:
    try:
        timestamp_str = q.get("timestamp", "")
        # Parse ISO format timestamp
        if timestamp_str:
            q_time = datetime.fromisoformat(timestamp_str.replace("+00:00", "").replace("Z", ""))
            if q_time >= recent_cutoff:
                recent_count += 1
    except:
        pass

# Display metrics
col1, col2, col3, col4 = st.columns(4)
with col1:
    st.metric("Total Questions", total_questions)
with col2:
    st.metric("Topic Clusters", unique_topics)
with col3:
    st.metric("Avg Tone Score", f"{avg_tone:.2f}")
with col4:
    st.metric("Last 7 Days", recent_count)

st.divider()

# ============================================================================
# FILTERS AND SEARCH
# ============================================================================

st.header("Filters & Search")

col1, col2, col3 = st.columns(3)

with col1:
    # Topic filter - use predefined topics plus any from dataset
    # Normalize all topics to proper case
    dataset_topics = set(q.get("topic_cluster", "General").title() for q in questions)

    # Combine predefined with dataset topics
    all_topics = PREDEFINED_TOPICS.copy()
    for dt in dataset_topics:
        # Add dataset topic if not already in list (case-insensitive check)
        if dt and not any(dt.lower() == pt.lower() for pt in PREDEFINED_TOPICS):
            all_topics.append(dt)

    # Sort alphabetically
    all_topics.sort()

    topic_filter = st.selectbox(
        "Filter by topic:",
        ["All Topics"] + all_topics,
        key="topic_filter"
    )

with col2:
    # Sort order
    sort_order = st.selectbox(
        "Sort by:",
        ["Newest First", "Oldest First", "Highest Tone Score", "Lowest Tone Score"],
        key="sort_order"
    )

with col3:
    # Search
    search_query = st.text_input(
        "Search questions:",
        placeholder="Enter keywords...",
        key="search_query"
    )

# Apply filters
filtered_questions = questions

# Topic filter (case-insensitive)
if topic_filter != "All Topics":
    filtered_questions = [
        q for q in filtered_questions
        if q.get("topic_cluster", "General").lower() == topic_filter.lower()
    ]

# Search filter
if search_query:
    search_lower = search_query.lower()
    filtered_questions = [
        q for q in filtered_questions
        if search_lower in q.get("question", "").lower()
        or search_lower in q.get("answer", "").lower()
    ]

# Sort
if sort_order == "Newest First":
    filtered_questions = sorted(filtered_questions, key=lambda x: x.get("timestamp", ""), reverse=True)
elif sort_order == "Oldest First":
    filtered_questions = sorted(filtered_questions, key=lambda x: x.get("timestamp", ""))
elif sort_order == "Highest Tone Score":
    filtered_questions = sorted(filtered_questions, key=lambda x: x.get("tone_score", 0.5), reverse=True)
elif sort_order == "Lowest Tone Score":
    filtered_questions = sorted(filtered_questions, key=lambda x: x.get("tone_score", 0.5))

st.caption(f"Showing {len(filtered_questions)} of {total_questions} questions")

st.divider()

# ============================================================================
# QUESTIONS DISPLAY
# ============================================================================

st.header("Questions")

# Check if there are questions to display
if not filtered_questions:
    st.info("No questions found matching your filters. Try adjusting the topic filter or search criteria.")
else:
    # Display each question in an expander
    for i, q in enumerate(filtered_questions):
        question_text = q.get("question", "N/A")
        answer_text = q.get("answer", "N/A")
        # Normalize topic to proper case
        topic = q.get("topic_cluster", "General").title()
        timestamp = q.get("timestamp", "N/A")
        tone_score = q.get("tone_score", 0.5)
        response_id = q.get("response_id", "N/A")

        # Format timestamp
        try:
            dt = datetime.fromisoformat(timestamp.replace("+00:00", "").replace("Z", ""))
            timestamp_display = dt.strftime("%Y-%m-%d %H:%M")
        except:
            timestamp_display = timestamp

        # Color code tone score
        if tone_score >= 0.7:
            tone_color = "🟢"
        elif tone_score >= 0.4:
            tone_color = "🟡"
        else:
            tone_color = "🔴"

        # Expander title with preview
        preview = question_text[:80] + "..." if len(question_text) > 80 else question_text
        expander_title = f"**Q{i+1}:** {preview} | {tone_color} {tone_score:.2f} | {timestamp_display}"

        with st.expander(expander_title):
            # Question details
            st.markdown("### Question")
            st.write(question_text)

            st.markdown("### Answer")
            st.write(answer_text)

            # Metadata
            col1, col2, col3, col4 = st.columns(4)
            with col1:
                st.caption(f"**Topic:** {topic}")
            with col2:
                st.caption(f"**Tone:** {tone_score:.2f}")
            with col3:
                st.caption(f"**Time:** {timestamp_display}")
            with col4:
                st.caption(f"**ID:** {response_id[:12]}...")

            st.divider()

            # ==================================================================
            # FEATURE 1: RESPONSE EDITOR
            # ==================================================================

            st.markdown("### ✏️ Review & Edit Response")
            st.caption("Edit the response if needed before approving for training")

            # Editable text area for the response
            edited_response = st.text_area(
                "Response (editable):",
                value=answer_text,
                height=200,
                key=f"edit_response_{response_id}",
                help="Edit this response to improve it before adding to training data"
            )

            # Show indicator if response was edited
            if edited_response.strip() != answer_text.strip():
                st.info("✏️ Response has been modified")

                # Show diff preview (optional but nice)
                with st.expander("👁️ View Changes"):
                    col1, col2 = st.columns(2)
                    with col1:
                        st.markdown("**Original:**")
                        st.text(answer_text[:300] + "..." if len(answer_text) > 300 else answer_text)
                    with col2:
                        st.markdown("**Edited:**")
                        st.text(edited_response[:300] + "..." if len(edited_response) > 300 else edited_response)

            st.divider()

            # ==================================================================
            # FEATURE 2: RE-TAG
            # ==================================================================

            st.markdown("### Topic Classification")

            # Get any additional topics from the dataset that aren't in predefined list
            # Normalize all topics to proper case
            dataset_topics = set(q.get("topic_cluster", "General").title() for q in questions)

            # Combine predefined topics with any unique topics from dataset
            all_topics = PREDEFINED_TOPICS.copy()
            for dt in dataset_topics:
                # Add dataset topic if not already in list (case-insensitive check)
                if dt and not any(dt.lower() == pt.lower() for pt in PREDEFINED_TOPICS):
                    all_topics.append(dt)

            # If current topic not in list, add it
            if topic and not any(topic.lower() == t.lower() for t in all_topics):
                all_topics.append(topic)

            # Sort alphabetically
            all_topics.sort()

            # Topic selector - find index case-insensitively
            try:
                topic_index = next(i for i, t in enumerate(all_topics) if t.lower() == topic.lower())
            except StopIteration:
                topic_index = 0

            selected_topic = st.selectbox(
                "Assign topic:",
                options=all_topics,
                index=topic_index,
                key=f"topic_select_{response_id}",
                help="Change the topic classification if needed"
            )

            # Show indicator if topic was changed
            if selected_topic != topic:
                st.info(f"Topic changed: '{topic}' → '{selected_topic}'")

            st.divider()

            # ==================================================================
            # ACTION BUTTONS
            # ==================================================================

            col1, col2 = st.columns(2)

            with col1:
                # Approve button - saves edited response and new topic
                if st.button("✅ Approve for Training", key=f"approve_{i}", use_container_width=True, type="primary"):
                    try:
                        # If topic was changed, update it in review queue first
                        if selected_topic != topic:
                            st.info(f"Updating topic in review queue: {response_id} → {selected_topic}")
                            update_success = update_review_queue_topic(response_id, selected_topic)
                            if update_success:
                                st.success(f"✓ Topic updated in review queue to '{selected_topic}'")
                            else:
                                st.warning("⚠️ Topic update in review queue failed, but continuing with approval...")

                        # Save the approved question with edited response and topic
                        result = save_approved_question(
                            question=question_text,
                            response=edited_response,  # Use edited version
                            topic=selected_topic,      # Use selected topic
                            response_id=response_id,
                            editor_notes=f"Reviewed by pastor. Original topic: {topic}" if selected_topic != topic else "Reviewed and approved by pastor"
                        )

                        # Check if save was successful
                        if result["success"]:
                            st.success("✅ Approved! Added to training dataset.")
                            st.balloons()

                            # Show what was saved with detailed info
                            with st.expander("📋 What was saved"):
                                st.write("**Question:**", question_text)
                                st.write("**Response:**", edited_response[:200] + "..." if len(edited_response) > 200 else edited_response)
                                st.write("**Topic:**", selected_topic)
                                st.write("**Response ID:**", result.get("response_id", response_id))
                                st.write("**Status:**", "Approved for training")
                                st.write("**File Location:**", result["file_path"])
                                st.write("**File Size:**", f"{result.get('file_size', 0)} bytes")
                                st.info(f"✓ {result['message']}")

                            # Force page reload to show updated topics
                            import time
                            time.sleep(2)  # Give user time to see the success message
                            st.rerun()
                        else:
                            st.error(f"❌ Failed to save to training dataset!")
                            st.error(f"Error: {result['message']}")
                            st.info(f"File path: {result['file_path']}")
                            st.warning("⚠️ Please try again or contact support if the issue persists.")

                    except Exception as e:
                        st.error(f"❌ Unexpected error saving: {e}")
                        import traceback
                        st.code(traceback.format_exc())

            with col2:
                # Reject button with confirmation dialog
                reject_key = f"reject_{response_id}"

                # Initialize confirmation state
                if "confirm_reject" not in st.session_state:
                    st.session_state.confirm_reject = {}

                # Check if we're in confirmation mode for this question
                if reject_key in st.session_state.confirm_reject:
                    st.warning("⚠️ Are you sure you want to reject this question?")
                    st.caption("This action cannot be undone. The question will not be used for training.")

                    sub_col1, sub_col2 = st.columns(2)
                    with sub_col1:
                        if st.button("✓ Yes, Reject", key=f"confirm_reject_yes_{i}", type="primary", use_container_width=True):
                            try:
                                # Create rejected entry
                                rejected_entry = {
                                    "response_id": response_id,
                                    "question": question_text,
                                    "answer": answer_text,
                                    "topic": topic,
                                    "rejected_at": datetime.now().isoformat(),
                                    "rejected_by": st.session_state.get("pastor_username", "unknown")
                                }

                                # Save to rejected log
                                rejected_log_path = Path(__file__).parent.parent.parent / "data" / "metrics" / "rejected_questions.jsonl"
                                rejected_log_path.parent.mkdir(parents=True, exist_ok=True)

                                with rejected_log_path.open("a", encoding="utf-8") as f:
                                    f.write(json.dumps(rejected_entry, ensure_ascii=True) + "\n")

                                st.success("✓ Question rejected and logged")
                                del st.session_state.confirm_reject[reject_key]
                                st.rerun()

                            except Exception as e:
                                st.error(f"Failed to log rejection: {e}")

                    with sub_col2:
                        if st.button("✗ Cancel", key=f"confirm_reject_no_{i}", use_container_width=True):
                            del st.session_state.confirm_reject[reject_key]
                            st.rerun()
                else:
                    # Show initial reject button
                    if st.button("❌ Reject", key=f"reject_{i}", use_container_width=True):
                        st.session_state.confirm_reject[reject_key] = True
                        st.rerun()

st.divider()

# ============================================================================
# EXPORT FUNCTIONALITY
# ============================================================================

st.header("📥 Export Data")

col1, col2, col3 = st.columns(3)

with col1:
    # Export as CSV
    if st.button("Download as CSV", use_container_width=True):
        df = pd.DataFrame(filtered_questions)
        csv = df.to_csv(index=False)

        st.download_button(
            label="📄 Download CSV File",
            data=csv,
            file_name=f"questions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
            use_container_width=True
        )

with col2:
    # Export as JSON
    if st.button("Download as JSON", use_container_width=True):
        json_str = json.dumps(filtered_questions, indent=2, ensure_ascii=False)

        st.download_button(
            label="📄 Download JSON File",
            data=json_str,
            file_name=f"questions_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json",
            mime="application/json",
            use_container_width=True
        )

with col3:
    # Export approved only (placeholder)
    if st.button("Download Approved Only", use_container_width=True):
        st.info("This feature will export only approved questions once the approval workflow is implemented.")

st.divider()

# ============================================================================
# ANALYTICS & INSIGHTS
# ============================================================================

st.header("📊 Analytics")

# Check if there are any filtered questions to show analytics for
if not filtered_questions:
    st.info("📭 No questions match the selected filters. Try selecting 'All Topics' or adjusting your search criteria.")
else:
    # Topic distribution
    st.subheader("Topic Distribution")
    topic_counts = {}
    for q in filtered_questions:
        # Normalize to proper case for consistent grouping
        topic = q.get("topic_cluster", "General").title()
        topic_counts[topic] = topic_counts.get(topic, 0) + 1

    if topic_counts:
        topic_df = pd.DataFrame([
            {"Topic": k, "Count": v}
            for k, v in sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
        ])
        st.bar_chart(topic_df.set_index("Topic"))
    else:
        st.info("No topic data available")

    # Tone score distribution
    st.subheader("Tone Score Distribution")
    tone_scores = [q.get("tone_score", 0.5) for q in filtered_questions]

    if tone_scores:
        tone_df = pd.DataFrame({"Tone Score": tone_scores})
        st.line_chart(tone_df)
    else:
        st.info("No tone score data available")

    # Questions over time
    st.subheader("Questions Over Time")
    try:
        timestamps = []
        for q in filtered_questions:
            try:
                ts = q.get("timestamp", "")
                if ts:
                    dt = datetime.fromisoformat(ts.replace("+00:00", "").replace("Z", ""))
                    timestamps.append(dt)
            except:
                pass

        if timestamps:
            # Group by date
            from collections import Counter
            date_counts = Counter([dt.date() for dt in timestamps])
            date_df = pd.DataFrame([
                {"Date": str(k), "Questions": v}
                for k, v in sorted(date_counts.items())
            ])
            st.line_chart(date_df.set_index("Date"))
        else:
            st.info("Not enough timestamp data to show timeline")
    except Exception as e:
        st.warning(f"Could not generate timeline: {e}")

# ============================================================================
# FOOTER
# ============================================================================

st.divider()
st.caption("This dashboard is password-protected and logs are sanitized for privacy.")
st.caption("For technical support, contact your system administrator.")
