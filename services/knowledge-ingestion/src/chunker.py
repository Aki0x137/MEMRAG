"""Content chunking for different source types."""

from __future__ import annotations

import re


def chunk(text: str, source_type: str, content_type: str = "text") -> list[str]:
    """
    Chunk content based on source type.
    
    Args:
        text: The content to chunk.
        source_type: 'github', 'confluence', 'slack', 'rds_schema'.
        content_type: 'code', 'html', 'text', 'schema'.
        
    Returns:
        List of text chunks.
    """
    if not text or not text.strip():
        return []

    if source_type == "github" and content_type == "code":
        return _chunk_code(text)
    elif source_type == "confluence" and content_type == "html":
        return _chunk_prose(text)
    elif source_type == "slack":
        return _chunk_prose(text)
    elif source_type == "rds_schema":
        return _chunk_schema(text)
    else:
        # Default: semantic chunking for prose
        return _chunk_prose(text)


def _chunk_code(text: str, max_chunk: int = 2000) -> list[str]:
    """
    Chunk code by function/class boundaries.
    
    Simplified tree-sitter-like approach: split on function/class definitions.
    """
    # Simple heuristic: split on function/class defs (Python-like syntax)
    chunks: list[str] = []
    lines = text.split("\n")
    current_chunk: list[str] = []
    
    for line in lines:
        # Check for function or class definition
        if line.strip().startswith(("def ", "class ", "async def ")):
            if current_chunk and len("\n".join(current_chunk)) > 200:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
        
        current_chunk.append(line)
        
        # Force break if chunk gets too large
        if len("\n".join(current_chunk)) > max_chunk:
            chunks.append("\n".join(current_chunk))
            current_chunk = []
    
    if current_chunk:
        chunks.append("\n".join(current_chunk))
    
    return [c for c in chunks if c.strip()]


def _chunk_prose(text: str, target_chunk: int = 1000, overlap: int = 200) -> list[str]:
    """
    Chunk prose with semantic boundaries and overlap.
    
    Split on paragraph/sentence boundaries, aim for ~1000 char chunks with 200 char overlap.
    """
    # Remove HTML tags
    text = re.sub(r"<[^>]+>", "", text)
    
    # Split by double newline (paragraphs)
    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_size = 0
    overlap_buffer = ""
    
    for para in paragraphs:
        para = para.strip()
        if not para:
            continue
        
        para_size = len(para)
        
        if current_size + para_size + len(overlap_buffer) < target_chunk:
            current_chunk.append(para)
            current_size += para_size
        else:
            # Finalize current chunk with overlap
            if current_chunk:
                chunk_text = "\n\n".join(current_chunk)
                chunks.append(chunk_text + "\n" + overlap_buffer if overlap_buffer else chunk_text)
                
                # Keep last ~200 chars for overlap
                overlap_buffer = (chunk_text + "\n\n" + para)[-overlap:]
            
            current_chunk = [para]
            current_size = para_size
    
    if current_chunk:
        chunk_text = "\n\n".join(current_chunk)
        chunks.append(chunk_text + "\n" + overlap_buffer if overlap_buffer else chunk_text)
    
    return [c.strip() for c in chunks if c.strip()]


def _chunk_schema(text: str) -> list[str]:
    """
    Chunk database schema: one chunk per table.

    Uses a regex to extract each block of optional comment lines immediately
    followed by a CREATE TABLE ... ); block.
    """
    # Optional leading comment lines (-- ...) + CREATE TABLE ... );
    pattern = re.compile(
        r"(?:(?:--[^\n]*)\n)*CREATE\s+TABLE[\s\S]+?\);",
        re.MULTILINE,
    )
    chunks = pattern.findall(text)
    return [c.strip() for c in chunks if c.strip()]
