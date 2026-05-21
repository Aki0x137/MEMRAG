"""MEMRAG shared library for memory, RAG, and BYOD platforms."""

__version__ = "0.1.0"
__author__ = "MEMRAG Contributors"

from memrag_shared.manifest import AgentDomain, AgentManifest
from memrag_shared.layers import (
    LAYER_SESSION,
    LAYER_AGENT,
    LAYER_SHARED,
    LAYER_ORG,
    MemoryChunk,
    KnowledgeChunk,
)
from memrag_shared.weights import DEFAULT_SOURCE_WEIGHT, WeightsConfig, get_weight, load_weights

__all__ = [
    "AgentDomain",
    "AgentManifest",
    "LAYER_SESSION",
    "LAYER_AGENT",
    "LAYER_SHARED",
    "LAYER_ORG",
    "MemoryChunk",
    "KnowledgeChunk",
    "DEFAULT_SOURCE_WEIGHT",
    "WeightsConfig",
    "get_weight",
    "load_weights",
]
