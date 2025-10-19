#!/usr/bin/env bash
# --- The Christian Project startup script ---

# Fail on first error
set -e

# Railway provides the port number in $PORT.
# If not defined (local dev), default to 8501.
PORT_VALUE=${PORT:-8501}

if ! [[ "$PORT_VALUE" =~ ^[0-9]+$ ]]; then
    echo "⚠️ Invalid PORT value '$PORT_VALUE'. Falling back to 8501."
    PORT_VALUE=8501
fi

echo "🚀 Starting Streamlit on port $PORT_VALUE..."

# Remove conflicting environment variable to avoid Streamlit parsing errors
unset STREAMLIT_SERVER_PORT

# Launch Streamlit and bind to all interfaces
exec streamlit run app/chat_interface.py \
    --server.port=$PORT_VALUE \
    --server.address=0.0.0.0
