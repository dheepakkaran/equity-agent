FROM python:3.12-slim

# System deps for psycopg2 build if wheel not available
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for layer caching
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

# Copy project
COPY . .

# HF Spaces expects the app on port 7860
ENV PORT=7860 \
    APP_ENV=production \
    PYTHONUNBUFFERED=1

# Alembic migrations are idempotent; running on start keeps schema in sync
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]

EXPOSE 7860
