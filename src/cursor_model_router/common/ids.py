"""Deterministic ID helpers used for event and signal deduplication.

Hooks can fire more than once for the same logical event (retries, crashed
hook processes that get re-invoked, duplicate delivery from the spool).
Event and derived-signal writes use stable keys from immutable fields so
re-processing the same observation is a no-op rather than a duplicate.
"""

from __future__ import annotations

import hashlib
import uuid


def stable_event_key(*parts: str) -> str:
    """Build a deterministic key from ordered string parts.

    Uses SHA-256 (not for security, only for a fixed-length stable key) over
    a joined, length-prefixed representation so that e.g. ("ab", "c") and
    ("a", "bc") never collide.
    """
    hasher = hashlib.sha256()
    for part in parts:
        encoded = part.encode("utf-8")
        hasher.update(len(encoded).to_bytes(8, "big"))
        hasher.update(encoded)
    return hasher.hexdigest()


def new_id() -> str:
    return str(uuid.uuid4())
