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
            correct_password = os.getenv("PASTOR_PASSWORD", "faith2025!")

            if password == correct_password:
                st.session_state.pastor_authenticated = True
                st.success("Authentication successful!")
                st.rerun()
            else:
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
    """Load all questions from review queue."""
    # Use absolute path from project root
    project_root = Path(__file__).parent.parent.parent
    questions_file = project_root / "data" / "metrics" / "review_queue.jsonl"

    if not questions_file.exists():
        return []

    questions = []
    try:
        with questions_file.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    questions.append(json.loads(line))
    except Exception as e:
        st.error(f"Error loading questions: {e}")

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
                            update_success = update_review_queue_topic(response_id, selected_topic)
                            if not update_success:
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
                # Reject button - for future use
                if st.button("❌ Reject", key=f"reject_{i}", use_container_width=True):
                    st.warning("⚠️ Rejected - will not use for training")
                    st.info("(Future: This will move to rejected items)")

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
        topic = q.get("topic_cluster", "general")
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
