"""Text truncation and secret redaction for anything persisted to MongoDB.

Prompts, tool output, and command output can contain credentials or content
the user never intended to store long-term. Every persistence path in the
collector and verification worker must route free-text fields through here
before they are written.
"""

from __future__ import annotations

import re

_SECRET_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)\b(sk|pk|rk)-[a-z0-9]{16,}\b"),
    re.compile(r"(?i)\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bghp_[a-zA-Z0-9]{36,}\b"),
    re.compile(r"(?i)\bcursor_[a-zA-Z0-9]{16,}\b"),
    re.compile(r"(?i)(api[_-]?key|secret|token|password|passwd)\s*[:=]\s*\S+"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"),
)

_REDACTED_PLACEHOLDER = "[REDACTED]"
_TRUNCATED_SUFFIX = "…[truncated]"


def redact_secrets(text: str) -> str:
    if not text:
        return text
    redacted = text
    for pattern in _SECRET_PATTERNS:
        redacted = pattern.sub(_REDACTED_PLACEHOLDER, redacted)
    return redacted


def truncate(text: str, max_chars: int) -> str:
    if text is None:
        return text
    if len(text) <= max_chars:
        return text
    keep = max(max_chars - len(_TRUNCATED_SUFFIX), 0)
    return text[:keep] + _TRUNCATED_SUFFIX


def sanitize_free_text(text: str | None, max_chars: int) -> str | None:
    if text is None:
        return None
    return truncate(redact_secrets(text), max_chars)
