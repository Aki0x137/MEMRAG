"""PII detection and sanitization utilities for knowledge ingestion."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import os
import re
from typing import Any

try:  # pragma: no cover - optional dependency wiring
    from presidio_analyzer import AnalyzerEngine
except Exception:  # pragma: no cover - Presidio is optional in tests
    AnalyzerEngine = None  # type: ignore[assignment]


PII_DROP_SENTINEL = "__PII_DROP__"


class PIIMatchAction(str, Enum):
    MASK = "mask"
    REDACT = "redact"
    DROP = "drop"


@dataclass(slots=True)
class PIIFinding:
    entity_category: str
    action_taken: str
    start: int
    end: int


@dataclass(slots=True)
class PIIResult:
    original_text: str
    sanitized_text: str
    findings: list[PIIFinding] = field(default_factory=list)
    dropped: bool = False


class PIIDetectedMismatchError(RuntimeError):
    """Raised when a connector claims no PII but detection finds otherwise."""

    def __init__(self, connector_id: str) -> None:
        super().__init__(f"PII detected for connector {connector_id} despite contains_pii=false")
        self.connector_id = connector_id


class PIIScanner:
    """Scan and sanitize text using hard PII rules plus configurable actions."""

    HARD_REDACT_ENTITIES = {"CREDIT_CARD", "BANK_ACCOUNT"}
    HARD_DROP_ENTITIES = {"PASSWORD", "SECRET"}

    _ENTITY_PATTERNS: dict[str, re.Pattern[str]] = {
        "EMAIL_ADDRESS": re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "PHONE_NUMBER": re.compile(r"\b(?:\+?\d{1,3}[-.\s]?)?(?:\(?\d{3}\)?[-.\s]?)\d{3}[-.\s]?\d{4}\b"),
        "CREDIT_CARD": re.compile(r"\b(?:\d[ -]*?){13,19}\b"),
        "BANK_ACCOUNT": re.compile(r"\b(?:acct|account|iban|routing)[:=\s-]*[A-Za-z0-9-]{8,}\b", re.IGNORECASE),
        "PASSWORD": re.compile(r"\bpassword\b\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
        "SECRET": re.compile(r"\b(?:secret|api[_-]?key|token)\b\s*[:=]\s*[^\s,;]+", re.IGNORECASE),
        "US_SSN": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
        "IP_ADDRESS": re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"),
        "URL": re.compile(r"\bhttps?://[^\s]+\b", re.IGNORECASE),
        "DATE_TIME": re.compile(r"\b\d{4}-\d{2}-\d{2}(?:[T\s]\d{2}:\d{2}:\d{2}Z?)?\b"),
        "PERSON": re.compile(r"\b([A-Z][a-z]+\s+[A-Z][a-z]+)\b"),
        "LOCATION": re.compile(r"\b(?:New York|San Francisco|London|Paris|Berlin|Tokyo)\b", re.IGNORECASE),
    }

    def __init__(self) -> None:
        self._engine = None
        if AnalyzerEngine is not None and os.getenv("PII_USE_PRESIDIO", "false").lower() in {"1", "true", "yes"}:
            try:
                self._engine = AnalyzerEngine()
            except Exception:
                self._engine = None

    def scan(self, chunk_text: str, pii_config: dict[str, Any] | None = None) -> PIIResult:
        pii_config = pii_config or {}
        action_overrides = _config_actions(pii_config)

        findings: list[PIIFinding] = []
        sanitized = chunk_text
        dropped = False

        matches = list(self._findings_from_regex(chunk_text))
        if self._engine is not None:
            try:
                matches.extend(self._findings_from_presidio(chunk_text))
            except Exception:
                pass

        matches.sort(key=lambda item: (item[1], item[2]))
        for entity_category, start, end in matches:
            if dropped:
                break

            action = _resolve_action(entity_category, action_overrides)
            if entity_category in self.HARD_REDACT_ENTITIES:
                action = PIIMatchAction.REDACT.value
            elif entity_category in self.HARD_DROP_ENTITIES:
                action = PIIMatchAction.DROP.value

            findings.append(PIIFinding(entity_category=entity_category, action_taken=action, start=start, end=end))

            if action == PIIMatchAction.DROP.value:
                sanitized = PII_DROP_SENTINEL
                dropped = True
                break

            replacement = _replacement_for(entity_category, action)
            sanitized = _replace_span(sanitized, start, end, replacement)

        return PIIResult(original_text=chunk_text, sanitized_text=sanitized, findings=findings, dropped=dropped)

    def _findings_from_regex(self, text: str) -> list[tuple[str, int, int]]:
        findings: list[tuple[str, int, int]] = []
        for entity_category, pattern in self._ENTITY_PATTERNS.items():
            for match in pattern.finditer(text):
                findings.append((entity_category, match.start(), match.end()))
        return findings

    def _findings_from_presidio(self, text: str) -> list[tuple[str, int, int]]:
        if self._engine is None:
            return []
        results = self._engine.analyze(text=text, language="en")
        findings: list[tuple[str, int, int]] = []
        for result in results:
            findings.append((str(result.entity_type).upper(), result.start, result.end))
        return findings


def _config_actions(pii_config: dict[str, Any]) -> dict[str, str]:
    actions: dict[str, str] = {}
    for key, value in pii_config.items():
        if key.endswith("_ACTION"):
            actions[key.removesuffix("_ACTION")] = str(value).lower()
        elif isinstance(value, dict) and "action" in value:
            actions[key.upper()] = str(value["action"]).lower()

    for env_key, env_value in os.environ.items():
        if env_key.startswith("PII_") and env_key.endswith("_ACTION"):
            actions.setdefault(env_key.removesuffix("_ACTION")[4:], env_value.lower())
    return actions


def _resolve_action(entity_category: str, action_overrides: dict[str, str]) -> str:
    return action_overrides.get(entity_category.upper(), PIIMatchAction.MASK.value)


def _replacement_for(entity_category: str, action: str) -> str:
    if entity_category == "EMAIL_ADDRESS":
        return "[EMAIL]"
    if entity_category == "PHONE_NUMBER":
        return "[PHONE]"
    if action == PIIMatchAction.REDACT.value:
        if entity_category in {"CREDIT_CARD", "BANK_ACCOUNT"}:
            return "█" * 8
        return f"[{entity_category}]"
    if action == PIIMatchAction.MASK.value:
        return f"[{entity_category}]"
    return f"[{entity_category}]"


def _replace_span(text: str, start: int, end: int, replacement: str) -> str:
    return text[:start] + replacement + text[end:]