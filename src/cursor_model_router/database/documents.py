"""Pure document builders for every MongoDB collection.

Kept framework-agnostic (no PyMongo imports) so the shape of a document can be
unit-tested without a database connection, and so both the sync hook path and
the async worker path build identical documents.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from cursor_model_router.common.constants import TaskStatus
from cursor_model_router.common.time_utils import utc_now

SCHEMA_VERSION = 5


@dataclass(frozen=True)
class ModelIdentity:
    model: str | None
    model_id: str | None
    model_params: list[dict[str, str]] = field(default_factory=list)


def build_task_upsert(
    *,
    task_id: str,
    conversation_id: str,
    repository_root: str | None,
    repository_commit: str | None,
    cursor_version: str | None,
    workspace_roots: list[str],
    identity: ModelIdentity,
    occurred_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a (filter, update) pair for an idempotent task upsert.

    Uses ``$setOnInsert`` for fields that should only be recorded once and
    ``$set``/``$addToSet`` for fields that may legitimately change across the
    life of a conversation (e.g. status, model switches mid-session).
    """
    filter_ = {"conversation_id": conversation_id}
    update = {
        "$setOnInsert": {
            "_id": task_id,
            "conversation_id": conversation_id,
            "started_at": occurred_at,
            "repository_root": repository_root,
            "repository_commit": repository_commit,
            "schema_version": SCHEMA_VERSION,
        },
        "$set": {
            "updated_at": occurred_at,
            "cursor_version": cursor_version,
        },
        "$addToSet": {
            "workspace_roots": {"$each": workspace_roots} if workspace_roots else None,
        },
    }
    if identity.model:
        update["$set"]["model"] = identity.model
    if identity.model_id:
        update["$set"]["model_id"] = identity.model_id
    if identity.model_params:
        update["$set"]["model_params"] = identity.model_params
    if not workspace_roots:
        update["$addToSet"].pop("workspace_roots", None)
    if not update["$addToSet"]:
        update.pop("$addToSet")
    return filter_, update


def build_task_status_update(
    *,
    conversation_id: str,
    status: str,
    loop_count: int | None,
    occurred_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    filter_ = {"conversation_id": conversation_id}
    set_fields: dict[str, Any] = {"status": status, "updated_at": occurred_at}
    if loop_count is not None:
        set_fields["loop_count"] = loop_count
    if status != "in_progress":
        set_fields["finished_at"] = occurred_at
    update = {"$set": set_fields}
    return filter_, update


def build_generation_upsert(
    *,
    generation_task_id: str,
    task_id: str,
    generation_id: str,
    repository_root: str | None,
    identity: ModelIdentity,
    occurred_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Return a (filter, update) pair for an idempotent generation upsert.

    Model, model ID, and repository root are captured with ``$setOnInsert``
    so they reflect whatever was true when this generation was first
    observed (ideally its prompt) rather than being overwritten by later
    activity in the same generation.
    """
    filter_ = {"task_id": task_id, "generation_id": generation_id}
    update = {
        "$setOnInsert": {
            "_id": generation_task_id,
            "task_id": task_id,
            "generation_id": generation_id,
            "started_at": occurred_at,
            "repository_root": repository_root,
            "model": identity.model,
            "model_id": identity.model_id,
            "model_params": identity.model_params,
            "status": TaskStatus.IN_PROGRESS,
            "schema_version": SCHEMA_VERSION,
        },
        "$set": {"updated_at": occurred_at},
    }
    return filter_, update


def build_generation_prompt_update(
    *, task_id: str, generation_id: str, prompt_preview: str, occurred_at: datetime
) -> tuple[dict[str, Any], dict[str, Any]]:
    filter_ = {
        "task_id": task_id,
        "generation_id": generation_id,
        "prompt_preview": {"$exists": False},
    }
    update = {"$set": {"prompt_preview": prompt_preview, "updated_at": occurred_at}}
    return filter_, update


def build_generation_status_update(
    *,
    task_id: str,
    generation_id: str,
    status: str,
    loop_count: int | None,
    occurred_at: datetime,
) -> tuple[dict[str, Any], dict[str, Any]]:
    filter_ = {"task_id": task_id, "generation_id": generation_id}
    set_fields: dict[str, Any] = {"status": status, "updated_at": occurred_at}
    if loop_count is not None:
        set_fields["loop_count"] = loop_count
    if status != TaskStatus.IN_PROGRESS:
        set_fields["finished_at"] = occurred_at
    update = {"$set": set_fields}
    return filter_, update


def build_task_event(
    *,
    event_key: str,
    task_id: str,
    generation_id: str,
    event_type: str,
    occurred_at: datetime,
    tool_name: str | None = None,
    command: str | None = None,
    file_path: str | None = None,
    success: bool | None = None,
    duration_ms: int | float | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "_id": event_key,
        "task_id": task_id,
        "generation_id": generation_id,
        "event_type": event_type,
        "tool_name": tool_name,
        "command": command,
        "file_path": file_path,
        "success": success,
        "duration_ms": int(duration_ms) if duration_ms is not None else None,
        "occurred_at": occurred_at,
        "metadata": metadata or {},
        "schema_version": SCHEMA_VERSION,
    }


def build_classification_document(
    *,
    task_id: str,
    generation_task_id: str,
    source: str,
    category: str,
    subcategory: str | None,
    primary_language: str | None,
    intent: str | None,
    cross_file_scope: bool | None,
    complexity: str | None,
    confidence: float,
    evidence: dict[str, Any],
    model: str | None = None,
    model_id: str | None = None,
    repository_root: str | None = None,
    provider: str | None = None,
    provider_model: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    """Build a classification document.

    A classification always reflects one prompt and its own generation-scoped
    activity, so it is keyed by ``generation_task_id`` (``task_generations._id``,
    unique together with ``source``). ``task_id`` is carried alongside it only
    for convenience -- to look up/aggregate a conversation's classifications
    without a join -- and is the conversation-level ``tasks._id``.
    """
    return {
        "task_id": task_id,
        "generation_task_id": generation_task_id,
        "source": source,
        "model": model,
        "model_id": model_id,
        "repository_root": repository_root,
        "category": category,
        "subcategory": subcategory,
        "primary_language": primary_language,
        "intent": intent,
        "cross_file_scope": cross_file_scope,
        "complexity": complexity,
        "confidence": confidence,
        "evidence": evidence,
        "provider": provider,
        "provider_model": provider_model,
        "prompt_version": prompt_version,
        "created_at": utc_now(),
        "schema_version": SCHEMA_VERSION,
    }


def build_outcome_signal(
    *,
    signal_key: str,
    task_id: str,
    signal_type: str,
    source: str,
    observed_at: datetime,
    payload: dict[str, Any],
) -> dict[str, Any]:
    return {
        "_id": signal_key,
        "task_id": task_id,
        "signal_type": signal_type,
        "source": source,
        "observed_at": observed_at,
        "payload": payload,
        "schema_version": SCHEMA_VERSION,
    }


def build_verification_definition(
    *,
    repository_root: str,
    repo_config_hash: str,
    checks: list[dict[str, Any]],
    trusted: bool,
) -> dict[str, Any]:
    return {
        "repository_root": repository_root,
        "repo_config_hash": repo_config_hash,
        "checks": checks,
        "trusted": trusted,
        "loaded_at": utc_now(),
        "schema_version": SCHEMA_VERSION,
    }


def build_verification_run(
    *,
    task_id: str,
    verification_method: str,
    check_type: str,
    command: str,
    status: str,
    exit_code: int | None,
    duration_ms: int | None,
    started_at: datetime,
    finished_at: datetime | None,
    commit: str | None,
    working_tree_dirty: bool | None,
    output_excerpt: str | None,
    source: str,
) -> dict[str, Any]:
    return {
        "task_id": task_id,
        "verification_method": verification_method,
        "check_type": check_type,
        "command": command,
        "status": status,
        "exit_code": exit_code,
        "duration_ms": duration_ms,
        "started_at": started_at,
        "finished_at": finished_at,
        "commit": commit,
        "working_tree_dirty": working_tree_dirty,
        "output_excerpt": output_excerpt,
        "source": source,
        "schema_version": SCHEMA_VERSION,
    }
