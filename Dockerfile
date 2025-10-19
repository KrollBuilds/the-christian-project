# --- The Christian Project Railway Deployment ---
FROM python:3.12-slim-bullseye

WORKDIR /app
COPY . /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# Use Railway's dynamic port
ENV PYTHONUNBUFFERED=1
ENV STREAMLIT_SERVER_HEADLESS=true

# Add a fallback so it runs locally with port 8501 if $PORT is unset
CMD bash -c "streamlit run app/chat_interface.py --server.port=${PORT:-8501} --server.address=0.0.0.0"
