FROM python:3.12-slim

# Don't write .pyc files; don't buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# System dependencies for asyncpg (C extension)
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies before copying source
# (better layer caching — source changes don't re-install deps)
COPY pyproject.toml .
RUN pip install --no-cache-dir -e ".[dev]"

COPY . .

# Run as non-root
RUN useradd --no-create-home --shell /bin/false guardian
USER guardian

CMD ["python", "-m", "app.main"]