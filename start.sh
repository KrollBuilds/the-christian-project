#!/usr/bin/env bash
# --- The Christian Project startup script ---

# Fail on first error
set -e

# Railway provides the port number in $PORT.
# If not defined (local dev), default to 8501.
PORT=${PORT:-8501}

echo "🚀 Starting Streamlit on port $PORT..."

# Launch Streamlit and bind to all interfaces
exec streamlit run app/chat_interface.py \
    --server.port=$PORT \
    --server.address=0.0.0.0
