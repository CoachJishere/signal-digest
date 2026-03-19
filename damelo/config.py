"""Config loading and validation."""

import json
import os
from pathlib import Path

REQUIRED_CONFIG_FIELDS = {"id", "name", "subject_template", "schedule", "system_prompt", "sources"}
REQUIRED_SOURCE_FIELDS = {"name", "url", "signal_type", "trust_weight", "fetch_full_content"}
VALID_SIGNAL_TYPES = {"velocity", "analysis"}


def load_config(path: str) -> dict:
    """Load and validate a config JSON file."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(config_path) as f:
        config = json.load(f)

    _validate_config(config, path)

    # Apply defaults
    config.setdefault("score_threshold", 4)
    config.setdefault("max_full_content_fetches", 5)
    config.setdefault("max_medium_fetches", 3)
    config.setdefault("top_n_items", 20)

    return config


def _validate_config(config: dict, path: str) -> None:
    """Validate config has all required fields with correct types."""
    missing = REQUIRED_CONFIG_FIELDS - set(config.keys())
    if missing:
        raise ValueError(f"Config {path} missing required fields: {missing}")

    if not isinstance(config["sources"], list) or not config["sources"]:
        raise ValueError(f"Config {path}: 'sources' must be a non-empty list")

    for i, source in enumerate(config["sources"]):
        missing_src = REQUIRED_SOURCE_FIELDS - set(source.keys())
        if missing_src:
            raise ValueError(f"Config {path}, source {i}: missing fields {missing_src}")

        if source["signal_type"] not in VALID_SIGNAL_TYPES:
            raise ValueError(
                f"Config {path}, source {i}: signal_type must be one of {VALID_SIGNAL_TYPES}"
            )

        if not isinstance(source["trust_weight"], int) or not 1 <= source["trust_weight"] <= 3:
            raise ValueError(f"Config {path}, source {i}: trust_weight must be int 1-3")


def load_manifest(path: str) -> list[dict]:
    """Load the configs.json manifest and return list of config entries."""
    manifest_path = Path(path)
    if not manifest_path.exists():
        raise FileNotFoundError(f"Manifest file not found: {path}")

    with open(manifest_path) as f:
        manifest = json.load(f)

    if "configs" not in manifest or not isinstance(manifest["configs"], list):
        raise ValueError(f"Manifest {path}: must contain a 'configs' list")

    return manifest["configs"]


def resolve_config_path(config_file: str, manifest_path: str) -> str:
    """Resolve a config filename relative to the manifest directory."""
    manifest_dir = Path(manifest_path).parent
    return str(manifest_dir / config_file)
