"""Layer definitions and data models for MEMRAG's 4-layer recall system."""

from dataclasses import dataclass, field
from typing import Any, Optional, Dict, List
from datetime import datetime, timezone
from enum import Enum

# Layer constants (LAYER_SESSION < LAYER_AGENT < LAYER_SHARED < LAYER_ORG)
LAYER_SESSION = 1  # Redis 24h TTL - Session buffer
LAYER_AGENT = 2    # Qdrant agent_memories - Long-term per-agent facts
LAYER_SHARED = 3   # Qdrant shared_memories - Workspace-scoped findings
LAYER_ORG = 4      # Qdrant org_knowledge - BYOD connectors (GitHub, Confluence, Slack, RDS)


class MemoryType(str, Enum):
    """Types of memory stored in agent/shared collections."""
    FACT = "fact"
    INSIGHT = "insight"
    PATTERN = "pattern"
    DECISION = "decision"


class KnowledgeType(str, Enum):
    """Types of knowledge in organization collection."""
    DOCUMENT = "document"
    ARTIFACT = "artifact"
    ISSUE = "issue"
    DISCUSSION = "discussion"


@dataclass
class MemoryChunk:
    """Memory chunk for agent and shared memory layers (L2, L3).
    
    Stored in Qdrant with hybrid search (768-dim dense + BM25 sparse).
    Compatible with Phase 2 context hydration contract.
    """
    # Core identity
    id: str
    agent_id: str
    workspace_id: str
    
    # Content (Phase 2 contract requires: text, score, source_type, metadata)
    text: str  # Phase 2 contract field
    content: str = ""  # Legacy; populated from text if empty
    memory_type: MemoryType = MemoryType.FACT
    
    # Embedding vectors
    embedding: Optional[List[float]] = None  # 768-dim from qwen3-embedding:4b
    
    # Metadata (Phase 2 contract: source_type required here)
    source_type: str = "agent_memory"  # Phase 2 contract: "agent_memory" | "shared_memory"
    score: Optional[float] = None  # Phase 2 contract: cosine similarity or RRF score
    layer: int = LAYER_AGENT  # LAYER_AGENT or LAYER_SHARED
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None  # TTL for layer recycling
    
    # Relationships
    source_document_id: Optional[str] = None  # Trace back to org_knowledge
    parent_memory_id: Optional[str] = None    # Link to parent fact
    related_memory_ids: List[str] = field(default_factory=list)
    
    # PII status
    contains_pii: bool = False
    pii_entities: Dict[str, List[str]] = field(default_factory=dict)  # {entity_type: [values]}
    
    # Scoring (legacy; Phase 2 uses 'score' field above)
    relevance_score: Optional[float] = None
    confidence: float = 1.0
    
    # Custom fields (Phase 2 contract: metadata dict required)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class KnowledgeChunk:
    """Knowledge chunk for organization layer (L4).
    
    BYOD connectors: GitHub, Confluence, Slack, RDS.
    Stored in Qdrant org_knowledge collection with dense embedding.
    Compatible with Phase 2 context hydration contract.
    """
    # Core identity
    id: str
    org_id: str
    connector_type: str  # 'github', 'confluence', 'slack', 'rds'
    
    # Content (Phase 2 contract requires: text, score, source_type, title, url, connector_id, metadata)
    text: str  # Phase 2 contract field
    content: str = ""  # Legacy; populated from text if empty
    knowledge_type: KnowledgeType = KnowledgeType.DOCUMENT
    title: str = ""  # Phase 2 contract required
    
    # Embedding vectors
    embedding: Optional[List[float]] = None  # 768-dim from qwen3-embedding:4b
    
    # Metadata (Phase 2 contract fields)
    source_type: str = "github"  # Phase 2 contract: "github" | "confluence" | "slack" | "rds_schema"
    score: Optional[float] = None  # Phase 2 contract: cosine similarity or RRF score
    url: Optional[str] = None  # Phase 2 contract field
    connector_id: str = ""  # Phase 2 contract field: UUID of connector
    
    # Legacy fields
    source_url: Optional[str] = None
    source_id: str = ""  # Original ID in source system (GitHub issue#, Confluence page ID, etc.)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Relationships
    workspace_ids: List[str] = field(default_factory=list)  # Which workspaces can access
    topic_tags: List[str] = field(default_factory=list)
    
    # PII status
    contains_pii: bool = False
    pii_entities: Dict[str, List[str]] = field(default_factory=dict)  # {entity_type: [values]}
    pii_action: str = "redact"  # 'redact', 'mask', 'hash', 'remove'
    
    # Scoring (legacy; Phase 2 uses 'score' field above)
    relevance_score: Optional[float] = None
    confidence: float = 1.0
    
    # Archive tracking
    archived: bool = False
    archived_at: Optional[datetime] = None
    
    # Custom fields (Phase 2 contract: metadata dict required)
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class SessionBuffer:
    """Session buffer for layer 1 (Redis 24h TTL).
    
    Lightweight memory for recent context.
    """
    # Core identity
    session_id: str
    agent_id: str
    workspace_id: str
    
    # Content
    context_items: List[str] = field(default_factory=list)
    
    # Timing
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    last_accessed: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    ttl_seconds: int = 86400  # 24 hours
    
    # Tracking
    size_bytes: int = 0
    item_count: int = 0
    
    # Custom fields
    metadata: Dict[str, Any] = field(default_factory=dict)
