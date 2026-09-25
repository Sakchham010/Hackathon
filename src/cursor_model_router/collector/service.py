"""Orchestrates one hook invocation: parse, filter, write-or-spool, respond.

This module is intentionally the only place that decides fail-open behavior.
Every exception is caught here; a telemetry failure must never surface as a
blocked or altered Cursor action.
"""

from __future__ import annotations

import logging
from typing import Any

from pymongo.errors import PyMongoError

from cursor_model_router.collector.events import ParsedEnvelope, apply_envelope, parse_hook_payload
from cursor_model_router.collector.spool import drain_spool, spool_event
from cursor_model_router.common.config import RouterConfig
from cursor_model_router.common.repo_filter import is_repository_observable
from cursor_model_router.database.client import create_sync_client
from cursor_model_router.database.repositories import TaskRepositorySync

logger = logging.getLogger(__name__)

_DEFAULT_RESPONSES: dict[str, dict[str, Any]] = {
    "beforeSubmitPrompt": {"continue": True},
    "preToolUse": {"permission": "allow"},
}


def _default_response(hook_event_name: str | None) -> dict[str, Any]:
    return dict(_DEFAULT_RESPONSES.get(hook_event_name or "", {}))


def _write_envelope(config: RouterConfig, envelope: ParsedEnvelope) -> bool:
    """Return True if persisted (to Mongo or spool), False only on an
    unexpected internal error the caller should log."""
    try:
        client = create_sync_client(config)
        try:
            database = client[config.database_name]
            apply_envelope(TaskRepositorySync(database), envelope)
            return True
        finally:
            client.close()
    except PyMongoError:
        try:
            spool_event(config.spool_dir, envelope.to_json())
            return True
        except OSError:
            logger.exception("Failed to spool event after MongoDB write failure")
            return False


def handle_raw_event(raw: dict[str, Any], config: RouterConfig) -> dict[str, Any]:
    hook_event_name = raw.get("hook_event_name")
    response = _default_response(hook_event_name)
    try:
        envelope = parse_hook_payload(raw, config)
        if envelope is None:
            return response
        if not is_repository_observable(envelope.repository_root, config.repositories):
            return response
        _write_envelope(config, envelope)
    except Exception:
        logger.exception("Unhandled error while processing hook event %s", hook_event_name)
    return response


def replay_envelope(config: RouterConfig, payload: dict[str, Any]) -> bool:
    envelope = ParsedEnvelope.from_json(payload)
    try:
        client = create_sync_client(config)
        try:
            database = client[config.database_name]
            apply_envelope(TaskRepositorySync(database), envelope)
            return True
        finally:
            client.close()
    except PyMongoError:
        return False


def drain(config: RouterConfig) -> int:
    return drain_spool(config.spool_dir, lambda payload: replay_envelope(config, payload))
