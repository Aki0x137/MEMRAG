FROM python:3.11-slim

WORKDIR /app

# Install system dependencies and uv
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.cargo/bin:$PATH"

# Copy project files
COPY . .

# Install dependencies with uv
RUN uv sync --frozen

# Expose API port
EXPOSE 8081

# Run FastAPI server
CMD ["uv", "run", "python", "-m", "services.context_hydrator.main"]
