"""Import bridge for decay activity tests."""

from __future__ import annotations

import importlib.util
from pathlib import Path


_MODULE_PATH = Path(__file__).resolve().parents[2] / "knowledge-ingestion" / "src" / "workflows" / "decay_memories.py"
_SPEC = importlib.util.spec_from_file_location("knowledge_ingestion_decay", _MODULE_PATH)
if _SPEC is None or _SPEC.loader is None:
    raise ImportError(f"Unable to load decay workflow module from {_MODULE_PATH}")
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)

decay_and_archive = _MODULE.decay_and_archive
