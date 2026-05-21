FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.cargo/bin:$PATH"

# Copy project files
COPY . .

# Install dependencies with uv
RUN uv sync --frozen

# Expose API port
EXPOSE 8083

# Run Temporal worker
CMD ["uv", "run", "python", "-m", "services.knowledge_ingestion.worker"]
