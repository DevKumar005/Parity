FROM python:3.12-slim

# Install clang and build tools needed for C compilation with -fwrapv
RUN apt-get update && apt-get install -y --no-install-recommends \
    clang \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python dependencies
COPY requirements.txt pyproject.toml ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code, samples, and frontend
COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY samples/ ./samples/

# Default environment variables
ENV PYTHONUNBUFFERED=1
ENV PORT=8000
ENV PARITY_PROVIDERS=mock

EXPOSE 8000

# Start unified FastAPI server (serves API + static frontend)
CMD ["sh", "-c", "uvicorn backend.server:app --host 0.0.0.0 --port ${PORT:-8000}"]
