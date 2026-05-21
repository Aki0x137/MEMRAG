# Context Hydrator

HTTP service for context hydration and assembly in MEMRAG.

## Purpose

Assembles multi-layer recall results into a unified context for LLM reasoning.

## Development

```bash
uv run --package memrag-context-hydrator python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8081
```
