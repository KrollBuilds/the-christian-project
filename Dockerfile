# --- The Christian Project | Streamlit on Railway ---
FROM python:3.12-slim-bullseye

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install build essentials for FAISS and other native libs
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Runtime configuration
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_HEADLESS=true

# Expose a default port (Railway overrides with $PORT)
EXPOSE 8080

# Basic health check so Railway detects readiness
HEALTHCHECK CMD curl --fail http://127.0.0.1:${PORT:-8080}/_stcore/health || exit 1

# Launch Streamlit bound to the provided port
CMD bash -c 'PORT=${PORT:-8080}; echo "🚀 Launching Streamlit on port $PORT"; streamlit run app/chat_interface.py --server.port=$PORT --server.address=0.0.0.0 --server.enableCORS=false --server.enableXsrfProtection=false'
