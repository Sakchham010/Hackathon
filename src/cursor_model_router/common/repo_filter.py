"""Decide whether a repository should be observed at all.

Applied before any event for that repository is written, so a deny rule (or
an allow list that excludes a path) means the router never sees that
repository's prompts, files, or commands.
"""

from __future__ import annotations

from fnmatch import fnmatch

from cursor_model_router.common.config import RepositoryFilterConfig
from cursor_model_router.common.pathing import normalize_path


def is_repository_observable(repository_root: str | None, config: RepositoryFilterConfig) -> bool:
    if not repository_root:
        return True
    normalized = normalize_path(repository_root) or ""
    if any(fnmatch(normalized, pattern) for pattern in config.deny):
        return False
    if config.allow:
        return any(fnmatch(normalized, pattern) for pattern in config.allow)
    return True


def is_path_ignored(path: str | None, config: RepositoryFilterConfig) -> bool:
    if not path:
        return False
    normalized = normalize_path(path) or ""
    return any(fnmatch(normalized, pattern) for pattern in config.ignored_path_globs)
