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

# Expose a default port (overridden by Railway's $PORT)
EXPOSE 8501

# Health check uses runtime port
CMD bash -c 'PORT=${PORT:-8501}; echo "🚀 Launching Streamlit on port $PORT"; streamlit run app/chat_interface.py --server.port=$PORT --server.address=0.0.0.0'
