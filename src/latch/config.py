"""Configuration manager for Latch.

Loads and validates operational parameters from config.json.
Follows zero-hardcoding standards: all defaults, thresholds, and paths are
defined through configuration.
"""

from __future__ import annotations
import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

PACKAGE_ROOT = Path(__file__).resolve().parents[2]


DEFAULT_PII_THRESHOLD: float = 0.65
SUPPORTED_CONFIG_VERSION: str = "1.0"


class ConfigError(Exception):
    """Raised when configuration file is missing, corrupt, or invalid."""
    pass


@dataclass
class LatchConfig:
    config_version: str = SUPPORTED_CONFIG_VERSION
    model: str = "SupersonicLabs/Julia-1"
    model_path: str = "./models/julia-1"
    model_max_context_tokens: int = 8192
    pii_threshold: float = DEFAULT_PII_THRESHOLD
    max_chunk_tokens: int = 750
    max_dissection_depth: int = 15
    localization_window_lines: int = 25
    daemon_port: int = 5138
    daemon_probe_timeout_ms: int = 50
    daemon_eval_timeout_sec: float = 10.0
    noul_prompt_template_path: str = "./templates/noul_prompt.txt"
    noul_criteria_path: str = "./fixtures/noul_criteria.json"
    benchmark_fixtures_dir: str = "./fixtures/"
    allowlist_paths: List[str] = field(default_factory=list)
    ignored_dirs: List[str] = field(default_factory=list)
    chunk_overlap_lines: int = 2
    chunk_overlap_chars: int = 64

    def __post_init__(self) -> None:
        """Resolve paths relative to package root if running outside project CWD."""
        self.model_path = self._resolve_path(self.model_path, "LATCH_MODEL_PATH")
        self.noul_prompt_template_path = self._resolve_path(self.noul_prompt_template_path)
        self.noul_criteria_path = self._resolve_path(self.noul_criteria_path)
        self.benchmark_fixtures_dir = self._resolve_path(self.benchmark_fixtures_dir)

    def _resolve_path(self, raw_path: str, env_override: Optional[str] = None) -> str:
        if env_override and os.environ.get(env_override):
            return os.environ[env_override]

        p = Path(raw_path)
        if p.is_absolute() or p.exists():
            return str(p)

        # Try package root if CWD does not have this relative path
        pkg_p = PACKAGE_ROOT / p
        if pkg_p.exists():
            return str(pkg_p)

        return str(p)

    def validate(self) -> None:
        """Validate config parameters against operational boundaries."""
        if self.config_version != SUPPORTED_CONFIG_VERSION:
            raise ConfigError(
                f"Unsupported config_version: '{self.config_version}'. Supported version is '{SUPPORTED_CONFIG_VERSION}'."
            )
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
        if not (1024 <= self.daemon_port <= 65535):
            raise ConfigError(
                f"Invalid daemon_port: {self.daemon_port}. Must be between 1024 and 65535."
            )
        if self.daemon_probe_timeout_ms <= 0:
            raise ConfigError(
                f"daemon_probe_timeout_ms must be positive, got {self.daemon_probe_timeout_ms}."
            )
        if self.daemon_eval_timeout_sec <= 0:
            raise ConfigError(
                f"daemon_eval_timeout_sec must be positive, got {self.daemon_eval_timeout_sec}."
            )


def resolve_config_path(explicit_path: Optional[str] = None) -> Path:
    """Finds config.json via explicit path, env var, CWD, or package root."""
    if explicit_path:
        p = Path(explicit_path)
        if not p.exists():
            raise ConfigError(f"Configuration file not found at '{explicit_path}'.")
        return p

    env_config = os.environ.get("LATCH_CONFIG")
    if env_config:
        p = Path(env_config)
        if p.exists():
            return p

    cwd_config = Path.cwd() / "config.json"
    if cwd_config.exists():
        return cwd_config

    latch_dir_config = Path.cwd() / ".latch" / "config.json"
    if latch_dir_config.exists():
        return latch_dir_config

    home_config = Path.home() / ".latch" / "config.json"
    if home_config.exists():
        return home_config

    pkg_config = PACKAGE_ROOT / "config.json"
    if pkg_config.exists():
        return pkg_config

    raise ConfigError(
        "No Latch configuration file found. Ensure 'config.json' exists in your workspace, "
        "~/.latch/config.json, or specify via LATCH_CONFIG environment variable."
    )


class ConfigManager:
    """Loads and validates configuration from config.json."""

    def __init__(self, config_path: Optional[str] = None) -> None:
        self._raw_path = config_path
        self.config_path: Optional[str] = None

    def load(self) -> LatchConfig:
        self.config_path = str(resolve_config_path(self._raw_path))
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

        # If falling back to PACKAGE_ROOT from outside the Latch development repository,
        # ensure allowlist_paths is neutral ([]) to prevent leaking demo/test allowlists.
        if (
            Path(self.config_path).resolve() == (PACKAGE_ROOT / "config.json").resolve()
            and Path.cwd().resolve() != PACKAGE_ROOT.resolve()
        ):
            filtered["allowlist_paths"] = []

        valid_fields: Set[str] = {f.name for f in fields(LatchConfig)}
        unknown_keys = set(filtered.keys()) - valid_fields
        if unknown_keys:
            raise ConfigError(
                f"Unknown configuration parameter(s) in '{self.config_path}': {sorted(unknown_keys)}"
            )

        config = LatchConfig(**filtered)
        config.validate()
        return config


_GLOBAL_CONFIG: LatchConfig | None = None


def get_config(config_path: Optional[str] = None) -> LatchConfig:
    """Cached config accessor that strictly validates presence and schema."""
    global _GLOBAL_CONFIG
    if _GLOBAL_CONFIG is not None and config_path is None:
        return _GLOBAL_CONFIG

    manager = ConfigManager(config_path)
    loaded = manager.load()
    if config_path is None:
        _GLOBAL_CONFIG = loaded
    return loaded
