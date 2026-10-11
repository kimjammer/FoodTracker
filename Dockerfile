FROM python:3.12-slim

# Install system dependencies (ca-certificates, curl)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv from official image
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install pinned Python 3.15 and production dependencies using uv
COPY .python-version pyproject.toml uv.lock ./
RUN uv python install 3.15
RUN uv sync --frozen --no-dev --no-install-project

# Copy application source code
COPY . .
RUN uv sync --frozen --no-dev

# Run the kitchen agent daemon
CMD ["uv", "run", "python", "main.py"]
