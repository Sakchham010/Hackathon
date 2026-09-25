"""Local disk spool used when MongoDB is unreachable from a hook process.

Cursor hooks must never block on a database write. Each spooled event is its
own file, written to a temp path and then atomically renamed into place, so a
crash mid-write can never leave a half-written file for the drainer to trip
over. Draining deletes a file only after it has been successfully replayed.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from cursor_model_router.common.constants import ConfigDefaults
from cursor_model_router.common.ids import new_id


def spool_event(spool_dir: Path, envelope: dict[str, Any]) -> Path:
    spool_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{envelope.get('_spooled_at', '')}-{new_id()}{ConfigDefaults.SPOOL_FILE_SUFFIX}"
    final_path = spool_dir / file_name
    tmp_path = spool_dir / f"{file_name}{ConfigDefaults.SPOOL_FILE_TMP_SUFFIX}"
    with tmp_path.open("w", encoding="utf-8") as handle:
        json.dump(envelope, handle)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp_path, final_path)
    return final_path


def iter_spooled_events(spool_dir: Path) -> Iterator[tuple[Path, dict[str, Any]]]:
    if not spool_dir.exists():
        return
    for path in sorted(spool_dir.glob(f"*{ConfigDefaults.SPOOL_FILE_SUFFIX}")):
        try:
            with path.open("r", encoding="utf-8") as handle:
                envelope = json.load(handle)
        except (json.JSONDecodeError, OSError):
            continue
        yield path, envelope


def drain_spool(
    spool_dir: Path,
    replay: Callable[[dict[str, Any]], bool],
    *,
    batch_size: int = ConfigDefaults.SPOOL_DRAIN_BATCH_SIZE,
) -> int:
    """Replay up to ``batch_size`` spooled events, deleting each on success.

    ``replay`` returns True if the event was successfully persisted (or was a
    known-duplicate no-op) and False if it should be retried later.
    """
    processed = 0
    for path, envelope in iter_spooled_events(spool_dir):
        if processed >= batch_size:
            break
        if replay(envelope):
            path.unlink(missing_ok=True)
        processed += 1
    return processed
