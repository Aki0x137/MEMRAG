"""Domain/source weight loading with env-file and AWS AppConfig backends."""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import Lock
from typing import Any

import boto3

DEFAULT_SOURCE_WEIGHT: dict[str, dict[str, float]] = {
    "agent_memory": {"code": 1.2, "ops": 1.3, "policy": 0.8, "data": 1.1},
    "shared_memory": {"code": 1.0, "ops": 1.2, "policy": 0.9, "data": 1.0},
    "github": {"code": 1.5, "ops": 0.9, "policy": 0.5, "data": 0.8},
    "confluence": {"code": 0.6, "ops": 1.2, "policy": 1.5, "data": 1.1},
    "rds_schema": {"code": 1.0, "ops": 0.8, "policy": 0.6, "data": 1.5},
    "slack": {"code": 0.4, "ops": 1.0, "policy": 0.5, "data": 0.7},
}

_VALID_DOMAINS = {"code", "ops", "policy", "data"}
_VALID_SOURCES = set(DEFAULT_SOURCE_WEIGHT)


@dataclass(slots=True)
class WeightsConfig:
    """Loaded source weights and refresh metadata."""

    weights: dict[str, dict[str, float]] = field(default_factory=lambda: dict(DEFAULT_SOURCE_WEIGHT))
    source: str = "default"
    version: str = "default"
    loaded_at: float = field(default_factory=time.time)


_weights_cache = WeightsConfig(weights={k: v.copy() for k, v in DEFAULT_SOURCE_WEIGHT.items()})
_weights_lock = Lock()


def _validate_weights(payload: dict[str, Any]) -> dict[str, dict[str, float]]:
    normalised: dict[str, dict[str, float]] = {}
    for source_type, domains in DEFAULT_SOURCE_WEIGHT.items():
        provided_domains = payload.get(source_type, {})
        domain_weights: dict[str, float] = {}
        for domain_name, default_value in domains.items():
            raw_value = provided_domains.get(domain_name, default_value)
            domain_weights[domain_name] = float(raw_value)
        normalised[source_type] = domain_weights

    unknown_sources = set(payload) - _VALID_SOURCES
    if unknown_sources:
        raise ValueError(f"Unknown source types in weights config: {sorted(unknown_sources)}")

    for source_type, domains in payload.items():
        unknown_domains = set(domains) - _VALID_DOMAINS
        if unknown_domains:
            raise ValueError(
                f"Unknown domains for source '{source_type}': {sorted(unknown_domains)}"
            )

    return normalised


def _load_from_env_file() -> WeightsConfig:
    weights_file = Path(os.getenv("WEIGHTS_FILE", ".weights.json"))
    if not weights_file.is_absolute():
        weights_file = Path.cwd() / weights_file

    if not weights_file.exists():
        return WeightsConfig(
            weights={k: v.copy() for k, v in DEFAULT_SOURCE_WEIGHT.items()},
            source="env-file",
            version="default",
        )

    payload = json.loads(weights_file.read_text(encoding="utf-8"))
    weights = _validate_weights(payload)
    return WeightsConfig(weights=weights, source="env-file", version=str(weights_file.stat().st_mtime))


def _load_from_appconfig(previous_version: str | None) -> WeightsConfig:
    region_name = os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION") or "us-east-1"
    application_id = os.getenv("AWS_APP_CONFIG_APPLICATION_ID")
    environment_id = os.getenv("AWS_APP_CONFIG_ENVIRONMENT_ID")
    profile_id = os.getenv("AWS_APP_CONFIG_PROFILE_ID")

    if not application_id or not environment_id or not profile_id:
        raise ValueError(
            "AWS AppConfig selected but AWS_APP_CONFIG_APPLICATION_ID, "
            "AWS_APP_CONFIG_ENVIRONMENT_ID, and AWS_APP_CONFIG_PROFILE_ID are not all set"
        )

    session = boto3.session.Session(region_name=region_name)
    client = session.client("appconfigdata")
    start_response = client.start_configuration_session(
        ApplicationIdentifier=application_id,
        EnvironmentIdentifier=environment_id,
        ConfigurationProfileIdentifier=profile_id,
    )
    token = start_response["InitialConfigurationToken"]
    config_response = client.get_latest_configuration(ConfigurationToken=token)
    content = config_response["Configuration"].read()
    version_label = config_response.get("VersionLabel") or previous_version or token

    if not content:
        return WeightsConfig(
            weights={k: v.copy() for k, v in DEFAULT_SOURCE_WEIGHT.items()},
            source="aws-appconfig",
            version=str(version_label),
        )

    payload = json.loads(content.decode("utf-8"))
    weights = _validate_weights(payload)
    return WeightsConfig(weights=weights, source="aws-appconfig", version=str(version_label))


def load_weights(force_reload: bool = False) -> WeightsConfig:
    """Load weights from the configured backend with process-local caching."""

    global _weights_cache

    source = os.getenv("WEIGHTS_CONFIG_SOURCE", "env-file").strip().lower()
    poll_interval = int(os.getenv("AWS_APP_CONFIG_POLL_INTERVAL_SECONDS", "60"))

    with _weights_lock:
        if not force_reload and time.time() - _weights_cache.loaded_at < poll_interval:
            return _weights_cache

        if source == "env-file":
            _weights_cache = _load_from_env_file()
        elif source == "aws-appconfig":
            _weights_cache = _load_from_appconfig(_weights_cache.version)
        else:
            raise ValueError(f"Unsupported WEIGHTS_CONFIG_SOURCE: {source}")

        return _weights_cache


def get_weight(source_type: str, domain: str | None) -> float:
    """Return the configured weight for a source/domain pair."""

    if domain is None:
        return 1.0

    config = load_weights()
    return config.weights.get(source_type, {}).get(domain, 1.0)