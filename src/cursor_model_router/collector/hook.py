"""Stdin/stdout entry point invoked by Cursor for every subscribed hook event.

Kept deliberately tiny: read JSON, delegate, write JSON, always exit 0. Any
exception here would surface to the user as a broken hook, so failures are
caught as close to the process boundary as possible.
"""

from __future__ import annotations

import json
import sys
from typing import Any, TextIO

from cursor_model_router.collector.service import handle_raw_event
from cursor_model_router.common.config import load_config


def read_hook_payload(stream: TextIO) -> dict[str, Any]:
    """Read Cursor's stdin payload, tolerating its Windows UTF-8 BOM."""
    try:
        raw_text = stream.read()
        # Windows PowerShell 5.1 can expose Cursor's UTF-8 BOM either as the
        # Unicode BOM code point or as its three decoded byte characters.
        while raw_text.startswith(("\ufeff", "\xef\xbb\xbf")):
            raw_text = raw_text.removeprefix("\ufeff").removeprefix("\xef\xbb\xbf")
        return json.loads(raw_text) if raw_text.strip() else {}
    except json.JSONDecodeError:
        return {}


def main() -> int:
    raw = read_hook_payload(sys.stdin)

    try:
        config = load_config()
        response = handle_raw_event(raw, config)
    except Exception:  # noqa: BLE001 - never let a config/parsing bug block Cursor
        response = {}

    sys.stdout.write(json.dumps(response))
    return 0


if __name__ == "__main__":
    sys.exit(main())
