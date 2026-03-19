# --- The Christian Project | Streamlit on Railway ---
FROM python:3.12-slim-bullseye

# Set working directory
WORKDIR /app

# Install build essentials for FAISS and other native libs, then purge after pip install
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt /app/

# Install CPU-only PyTorch BEFORE sentence-transformers to avoid pulling in CUDA (~2GB saved)
RUN pip3 install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

RUN pip3 install --no-cache-dir -r requirements.txt \
    && apt-get purge -y --auto-remove build-essential \
    && rm -rf /var/lib/apt/lists/* /tmp/* /root/.cache

# Copy project files
COPY . /app

# Runtime configuration
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app
ENV STREAMLIT_SERVER_HEADLESS=true

# Railway uses port 8080 by default, but configurable
EXPOSE 7860

# Launch Streamlit
CMD ["streamlit", "run", "app/Home.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
