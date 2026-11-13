FROM docker.io/python:3.12.11-slim-bookworm

ARG APP_HOME=/app

ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

WORKDIR ${APP_HOME}

# Install system dependencies
RUN apt-get update && apt-get install --no-install-recommends -y \
  libpq-dev \
  git \
  gcc \
  g++ \
  python3-dev \
  build-essential \
  && apt-get purge -y --auto-remove -o APT::AutoRemove::RecommendsImportant=false \
  && rm -rf /var/lib/apt/lists/*

# Install UV
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

# Copy project files for dependency installation
COPY packages/backend/pyproject.toml packages/backend/uv.lock ./

# Install dependencies
RUN uv sync

# Copy application code (overridden by volume mount in dev)
COPY packages/backend/ ${APP_HOME}

EXPOSE 8000

CMD ["uv", "run", "python", "manage.py", "runserver", "0.0.0.0:8000"]
