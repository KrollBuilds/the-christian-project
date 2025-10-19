# --- The Christian Project Railway Deployment ---
FROM python:3.12-slim-bullseye

WORKDIR /app
COPY . /app

RUN apt-get update && apt-get install -y --no-install-recommends build-essential \
 && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir -r requirements.txt

# Ensure startup script is executable
RUN chmod +x /app/start.sh

EXPOSE 8501

CMD ["/app/start.sh"]
