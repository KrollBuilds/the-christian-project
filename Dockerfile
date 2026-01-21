# --- The Christian Project | Streamlit on Hugging Face Spaces ---
FROM python:3.12-slim-bullseye

# Set working directory
WORKDIR /app

# Install build essentials for FAISS and other native libs
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt /app/
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy project files
COPY . /app

# Runtime configuration
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_HEADLESS=true

# HF Spaces requires port 7860
EXPOSE 7860

# Launch Streamlit on port 7860 (HF Spaces default)
CMD ["streamlit", "run", "app/Home.py", "--server.port=7860", "--server.address=0.0.0.0", "--server.headless=true"]
