"""Sparse token weighting helpers for hybrid Qdrant recall."""

from __future__ import annotations

import hashlib
import re
from collections import Counter

TOKEN_RE = re.compile(r"[A-Za-z0-9_]+")


def tokenize(text: str) -> list[str]:
    return [token.lower() for token in TOKEN_RE.findall(text)]


def sparse_vector(text: str) -> dict[str, list[float] | list[int]]:
    counts = Counter(tokenize(text))
    indices: list[int] = []
    values: list[float] = []
    for token, count in sorted(counts.items()):
        digest = hashlib.sha1(token.encode("utf-8")).hexdigest()
        indices.append(int(digest[:8], 16))
        values.append(float(count))
    return {"indices": indices, "values": values}
