"""Central configuration for cursor-model-router.

Loaded once from ``~/.cursor-model-router/config.yaml`` (override with the
``CURSOR_MODEL_ROUTER_CONFIG`` environment variable) and merged with a small
set of environment-variable overrides so hooks, the CLI, and tests can all
share one source of truth without requiring a config file to exist.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field

from cursor_model_router.common.constants import ConfigDefaults

_CONFIG_ENV_VAR = "CURSOR_MODEL_ROUTER_CONFIG"
_MONGO_URI_ENV_VAR = "CURSOR_MODEL_ROUTER_MONGO_URI"
_DATABASE_NAME_ENV_VAR = "CURSOR_MODEL_ROUTER_DATABASE"
_HOME_DIR_ENV_VAR = "CURSOR_MODEL_ROUTER_HOME"


class RedactionConfig(BaseModel):
    max_prompt_chars: int = ConfigDefaults.DEFAULT_MAX_PROMPT_CHARS
    max_tool_output_chars: int = ConfigDefaults.DEFAULT_MAX_TOOL_OUTPUT_CHARS
    max_command_output_chars: int = ConfigDefaults.DEFAULT_MAX_COMMAND_OUTPUT_CHARS
    persist_file_contents: bool = False
    persist_full_tool_output: bool = False


class RepositoryFilterConfig(BaseModel):
    """Controls which repositories are observed at all.

    Patterns are matched against the normalized, forward-slash repository
    root path using ``fnmatch``-style globs. An empty allow list means "all
    repositories not explicitly denied".
    """

    allow: list[str] = Field(default_factory=list)
    deny: list[str] = Field(default_factory=list)
    ignored_path_globs: list[str] = Field(
        default_factory=lambda: [
            "**/.git/**",
            "**/node_modules/**",
            "**/bin/**",
            "**/obj/**",
            "**/*.env",
            "**/*.pem",
            "**/*.key",
        ]
    )


class TrustedRepositoryConfig(BaseModel):
    """A repository explicitly trusted to run its own verification commands.

    Trust must be granted centrally by the developer running the router; a
    repository cannot self-grant execution rights merely by shipping a
    ``.cursor-model-router.yaml`` file.
    """

    path_glob: str
    max_command_timeout_seconds: int = 900


class ClassificationConfig(BaseModel):
    low_confidence_threshold: float = 0.5
    llm_enabled: bool = False
    llm_provider: str | None = None
    llm_model: str | None = None
    llm_prompt_version: str | None = None


class VerificationConfig(BaseModel):
    trusted_repositories: list[TrustedRepositoryConfig] = Field(default_factory=list)
    repo_config_file_name: str = ".cursor-model-router.yaml"
    default_command_timeout_seconds: int = 600


class RouterConfig(BaseModel):
    mongo_uri: str = ConfigDefaults.DEFAULT_MONGO_URI
    database_name: str = ConfigDefaults.DEFAULT_DATABASE_NAME
    home_dir: str = Field(
        default_factory=lambda: str(Path.home() / ConfigDefaults.CONFIG_DIR_NAME)
    )
    retention_days: int = ConfigDefaults.DEFAULT_RETENTION_DAYS
    redaction: RedactionConfig = Field(default_factory=RedactionConfig)
    repositories: RepositoryFilterConfig = Field(default_factory=RepositoryFilterConfig)
    classification: ClassificationConfig = Field(default_factory=ClassificationConfig)
    verification: VerificationConfig = Field(default_factory=VerificationConfig)

    @property
    def spool_dir(self) -> Path:
        return Path(self.home_dir) / ConfigDefaults.DEFAULT_SPOOL_DIR_NAME

    @property
    def log_dir(self) -> Path:
        return Path(self.home_dir) / ConfigDefaults.DEFAULT_LOG_DIR_NAME


def _default_config_path() -> Path:
    override = os.environ.get(_CONFIG_ENV_VAR)
    if override:
        return Path(override)
    home_override = os.environ.get(_HOME_DIR_ENV_VAR)
    base = Path(home_override) if home_override else Path.home() / ConfigDefaults.CONFIG_DIR_NAME
    return base / ConfigDefaults.CONFIG_FILE_NAME


def _read_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError(f"Config file {path} must contain a YAML mapping at the top level.")
    return data


def load_config(path: Path | None = None) -> RouterConfig:
    resolved_path = path or _default_config_path()
    raw = _read_yaml(resolved_path)
    config = RouterConfig.model_validate(raw)

    mongo_uri_override = os.environ.get(_MONGO_URI_ENV_VAR)
    if mongo_uri_override:
        config.mongo_uri = mongo_uri_override

    database_override = os.environ.get(_DATABASE_NAME_ENV_VAR)
    if database_override:
        config.database_name = database_override

    home_override = os.environ.get(_HOME_DIR_ENV_VAR)
    if home_override:
        config.home_dir = home_override

    return config
