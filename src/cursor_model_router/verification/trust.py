"""Decide whether a repository is trusted to run its own verification commands.

Trust is granted centrally, in the developer's own
``~/.cursor-model-router/config.yaml`` (``verification.trusted_repositories``),
never by anything a repository ships. A repository's
``.cursor-model-router.yaml`` only supplies *what* to run once trust already
exists.
"""

from __future__ import annotations

from fnmatch import fnmatch

from cursor_model_router.common.config import TrustedRepositoryConfig
from cursor_model_router.common.pathing import normalize_path


def find_trust_entry(
    repository_root: str, trusted_repositories: list[TrustedRepositoryConfig]
) -> TrustedRepositoryConfig | None:
    normalized = normalize_path(repository_root) or ""
    for entry in trusted_repositories:
        if fnmatch(normalized, entry.path_glob):
            return entry
    return None
