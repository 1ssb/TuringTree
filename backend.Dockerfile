# syntax=docker/dockerfile:1
#
# RagIndex backend — the FastAPI app (backend/app/main.py) over the sockets,
# served by uvicorn. It talks to the Ollama service over the compose network.
#
FROM python:3.11-slim

# git is needed to clone the vendored PageIndex "model" at build time.
RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first for better layer caching: copy only the requirement
# files so editing code doesn't invalidate the (slow) dependency layer.
COPY requirements.txt ./requirements.txt
COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r requirements.txt -r backend/requirements.txt

# Application code (see .dockerignore for what's excluded).
COPY . .

# Clone the PageIndex model the sockets import at runtime (git-ignored in repo).
RUN git clone --depth 1 https://github.com/VectifyAI/PageIndex.git vendor/PageIndex

ENV PYTHONUNBUFFERED=1 \
    OLLAMA_HOST=http://ollama:11434

EXPOSE 8000
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
