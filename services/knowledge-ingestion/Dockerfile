FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"
ENV PYTHONPATH="/app/services/knowledge-ingestion/src"

# Copy entire workspace
COPY . .

# Sync dependencies using uv workspace
RUN uv sync --frozen --all-packages

# Expose Prometheus metrics port
EXPOSE 8080

# Run via uv
CMD ["uv", "run", "--package", "memrag-knowledge-ingestion", "python", "-m", "worker"]
