"""MEMRAG shared library for memory, RAG, and BYOD platforms."""

__version__ = "0.1.0"
__author__ = "MEMRAG Contributors"

# Import core modules for convenience
from memrag_shared.layers import (
    LAYER_SESSION,
    LAYER_AGENT,
    LAYER_SHARED,
    LAYER_ORG,
    MemoryChunk,
    KnowledgeChunk,
)

__all__ = [
    "LAYER_SESSION",
    "LAYER_AGENT",
    "LAYER_SHARED",
    "LAYER_ORG",
    "MemoryChunk",
    "KnowledgeChunk",
]
