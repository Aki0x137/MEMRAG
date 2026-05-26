FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && curl -LsSf https://astral.sh/uv/install.sh | sh

ENV PATH="/root/.local/bin:$PATH"
ENV PYTHONPATH="/app/services/memory-api/src:/app/services/agent-workers/src"

COPY . .

RUN uv sync --frozen --all-packages

EXPOSE 8083

CMD ["uv", "run", "--package", "memrag-memory-api", "uvicorn", "main:app", \
     "--app-dir", "services/memory-api/src", \
     "--host", "0.0.0.0", "--port", "8083"]