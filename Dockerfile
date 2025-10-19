# --- The Christian Project | Streamlit on Railway ---
FROM python:3.12-slim-bullseye

# Set working directory
WORKDIR /app

# Copy project files
COPY . /app

# Install build essentials for FAISS and other native libs
RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN pip3 install --no-cache-dir -r requirements.txt

# Expose default port (for local testing)
EXPOSE 8501

# Run Streamlit via shell to ensure $PORT expands correctly
CMD bash -c 'PORT=${PORT:-8501}; echo "🚀 Launching Streamlit on port $PORT"; streamlit run app/chat_interface.py --server.port=$PORT --server.address=0.0.0.0'
