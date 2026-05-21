FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.cargo/bin:$PATH"

# Copy project files
COPY . .

# Install dependencies with uv
RUN uv sync --frozen

# Expose metrics port
EXPOSE 8080

# Run Temporal worker
CMD ["uv", "run", "python", "-m", "services.agent_workers.worker"]
