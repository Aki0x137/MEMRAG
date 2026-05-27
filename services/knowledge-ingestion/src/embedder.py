"""Embedding generation for chunked knowledge content."""

from __future__ import annotations

import re
from collections import Counter

from infra.ollama_client import get_client as get_ollama_client


async def embed_batch(texts: list[str]) -> list[list[float]]:
    """
    Generate 768-dimensional embeddings for a batch of texts.
    
    Args:
        texts: List of text chunks.
        
    Returns:
        List of embedding vectors (768 dimensions each).
    """
    if not texts:
        return []
    
    client = get_ollama_client()
    embeddings = await client.embed(texts)
    return embeddings


def embed_sparse(texts: list[str]) -> list[dict]:
    """
    Generate BM25 sparse vectors for a batch of texts.
    
    Args:
        texts: List of text chunks.
        
    Returns:
        List of dicts with 'indices' and 'values' for sparse vectors.
    """
    sparse_vectors: list[dict] = []
    
    for text in texts:
        # Tokenize: lowercase, alphanumeric + underscore
        tokens = re.findall(r"\b[a-zA-Z0-9_]+\b", text.lower())
        
        if not tokens:
            sparse_vectors.append({"indices": [], "values": []})
            continue
        
        # BM25-like term frequency (simplified)
        # Use log(1 + term_count) as the weight
        token_counts = Counter(tokens)
        vocab_size = len(token_counts)
        
        indices: list[int] = []
        values: list[float] = []
        
        for i, (token, count) in enumerate(sorted(token_counts.items())):
            # Simple TF-IDF-like weight: log(1 + count)
            weight = 1.0 + (count - 1) * 0.5
            indices.append(i)
            values.append(weight)
        
        sparse_vectors.append({"indices": indices, "values": values})
    
    return sparse_vectors
