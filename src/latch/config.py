"""Configuration manager for Latch.

Loads and validates operational parameters from config.json.
Follows zero-hardcoding standards: all defaults, thresholds, and paths are
defined through configuration.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict


class ConfigError(Exception):
    """Raised when configuration file is missing, corrupt, or invalid."""
    pass


@dataclass
class LatchConfig:
    config_version: str = "1.0"
    model: str = "SupersonicLabs/Julia-1"
    model_path: str = "./models/julia-1"
    model_max_context_tokens: int = 8192
    pii_threshold: float = 0.65
    max_chunk_tokens: int = 750
    max_dissection_depth: int = 15
    localization_window_lines: int = 25
    daemon_port: int = 5138
    daemon_probe_timeout_ms: int = 50
    daemon_eval_timeout_sec: float = 10.0
    noul_state_template_path: str = "./templates/noul_state.txt"
    noul_criteria_path: str = "./fixtures/noul_criteria.json"
    benchmark_fixtures_dir: str = "./fixtures/"

    def validate(self) -> None:
        """Validate config parameters against operational boundaries."""
        if not (0.0 <= self.pii_threshold <= 1.0):
            raise ConfigError(
                f"Invalid pii_threshold: {self.pii_threshold}. Must be between 0.0 and 1.0."
            )
        if self.max_chunk_tokens > self.model_max_context_tokens:
            raise ConfigError(
                f"max_chunk_tokens ({self.max_chunk_tokens}) cannot exceed "
                f"model_max_context_tokens ({self.model_max_context_tokens})."
            )
        if self.max_chunk_tokens <= 0:
            raise ConfigError(f"max_chunk_tokens must be positive, got {self.max_chunk_tokens}.")
        if self.max_dissection_depth <= 0:
            raise ConfigError(f"max_dissection_depth must be positive, got {self.max_dissection_depth}.")
        if self.localization_window_lines <= 0:
            raise ConfigError(f"localization_window_lines must be positive, got {self.localization_window_lines}.")
        if self.daemon_eval_timeout_sec <= 0:
            raise ConfigError(
                f"daemon_eval_timeout_sec must be positive, got {self.daemon_eval_timeout_sec}."
            )


class ConfigManager:
    """Loads and validates configuration from config.json."""

    def __init__(self, config_path: str = "config.json") -> None:
        self.config_path = config_path

    def load(self) -> LatchConfig:
        if not os.path.exists(self.config_path):
            raise ConfigError(
                f"Configuration file not found at '{self.config_path}'. "
                "Ensure config.json exists in the project root."
            )
        
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError as err:
            raise ConfigError(f"Malformed JSON in '{self.config_path}': {err}") from err
        except Exception as err:
            raise ConfigError(f"Failed to read '{self.config_path}': {err}") from err

        # Filter out JSON schema meta fields
        filtered: Dict[str, Any] = {
            k: v for k, v in data.items() if not k.startswith("$")
        }

        config = LatchConfig(**filtered)
        config.validate()
        return config


_GLOBAL_CONFIG: LatchConfig | None = None


def get_config(config_path: str = "config.json") -> LatchConfig:
    """Singleton-style cached config accessor with fallback to defaults."""
    global _GLOBAL_CONFIG
    if _GLOBAL_CONFIG is None:
        manager = ConfigManager(config_path)
        if os.path.exists(config_path):
            _GLOBAL_CONFIG = manager.load()
        else:
            _GLOBAL_CONFIG = LatchConfig()
    return _GLOBAL_CONFIG
