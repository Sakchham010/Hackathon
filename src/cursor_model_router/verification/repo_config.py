"""Load a repository's own ``.cursor-model-router.yaml`` verification config.

Loading this file never grants it permission to run anything; that decision
belongs entirely to :mod:`cursor_model_router.verification.trust`, which
checks the *central* router config for an explicit trust entry matching the
repository path before any command from this file is ever executed.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError


class CheckDefinition(BaseModel):
    name: str
    command: str
    check_type: Literal["test", "build", "lint", "behavior", "research", "other"] = "other"
    working_directory: str = "."
    timeout_seconds: int | None = None


class RepoVerificationFile(BaseModel):
    version: int = 1
    checks: list[CheckDefinition] = Field(default_factory=list)


def load_repo_config(repo_root: Path, file_name: str) -> tuple[RepoVerificationFile, str] | None:
    config_path = repo_root / file_name
    if not config_path.exists():
        return None

    raw_bytes = config_path.read_bytes()
    config_hash = hashlib.sha256(raw_bytes).hexdigest()

    try:
        raw = yaml.safe_load(raw_bytes.decode("utf-8")) or {}
        parsed = RepoVerificationFile.model_validate(raw)
    except (yaml.YAMLError, ValidationError, UnicodeDecodeError):
        return None

    return parsed, config_hash
