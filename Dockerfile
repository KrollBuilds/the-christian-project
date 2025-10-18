# --- Railway Deployment for The Christian Project ---
FROM python:3.12-slim-bullseye

# Set working directory
WORKDIR /app

# System dependencies (minimal build tools for FAISS and numpy)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
 && rm -rf /var/lib/apt/lists/*

# Copy only requirement files first to leverage Docker caching
COPY requirements.txt .

# Install dependencies without cache to minimize size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application
COPY . .

# Expose Streamlit port
EXPOSE 8501

# Prevent Hugging Face model cache bloat
ENV TRANSFORMERS_CACHE=/app/data/cache
ENV HF_HOME=/app/data/cache

# Default command for Railway
CMD ["streamlit", "run", "app/chat_interface.py", "--server.port=8501", "--server.address=0.0.0.0"]
