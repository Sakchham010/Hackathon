"""Path normalization shared by the collector, verification, and filters.

Windows paths arrive with backslashes and inconsistent drive-letter casing;
normalizing once here means every downstream comparison (allow/deny globs,
Mongo lookups, idempotency keys) can assume a single canonical form.
"""

from __future__ import annotations

from pathlib import PurePath


def normalize_path(raw_path: str | None) -> str | None:
    if not raw_path:
        return raw_path
    as_posix = PurePath(raw_path).as_posix()
    # Cursor reports Windows workspace roots as ``/C:/...``. Remove the
    # URI-style leading slash before normalizing the drive letter.
    if len(as_posix) >= 3 and as_posix[0] == "/" and as_posix[2] == ":":
        as_posix = as_posix[1:]
    if len(as_posix) >= 2 and as_posix[1] == ":":
        as_posix = as_posix[0].lower() + as_posix[1:]
    return as_posix
