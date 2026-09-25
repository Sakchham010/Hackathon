"""Normalize raw Cursor hook payloads into a spool/DB-agnostic envelope.

:func:`parse_hook_payload` performs all redaction and truncation up front, so
neither the live write path nor a later spool replay ever handles unredacted
text. :func:`apply_envelope` is the single place that turns an envelope into
task/event writes, called identically whether the event just arrived or is
being replayed from the spool.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cursor_model_router.common.config import RouterConfig
from cursor_model_router.common.constants import UNSCOPED_GENERATION_ID, HookEventType, TaskStatus
from cursor_model_router.common.ids import stable_event_key
from cursor_model_router.common.pathing import normalize_path
from cursor_model_router.common.redaction import sanitize_free_text
from cursor_model_router.common.time_utils import to_utc, utc_now
from cursor_model_router.database import documents as docs
from cursor_model_router.database.repositories import TaskRepositorySync

_HOOK_EVENT_TO_INTERNAL = {
    "sessionStart": HookEventType.SESSION_START,
    "beforeSubmitPrompt": HookEventType.BEFORE_SUBMIT_PROMPT,
    "preToolUse": HookEventType.PRE_TOOL_USE,
    "postToolUse": HookEventType.POST_TOOL_USE,
    "postToolUseFailure": HookEventType.POST_TOOL_USE_FAILURE,
    "afterFileEdit": HookEventType.AFTER_FILE_EDIT,
    "stop": HookEventType.STOP,
    "sessionEnd": HookEventType.SESSION_END,
}

_STOP_STATUS_MAP = {
    "completed": TaskStatus.COMPLETED,
    "aborted": TaskStatus.ABORTED,
    "error": TaskStatus.ERROR,
}

# These hook events describe the conversation as a whole rather than one
# generation/turn, so they never create or update a task_generations record.
_CONVERSATION_ONLY_EVENTS = {"sessionStart", "sessionEnd"}


@dataclass(frozen=True)
class ParsedEnvelope:
    hook_event_name: str
    conversation_id: str
    generation_id: str
    identity: docs.ModelIdentity
    workspace_roots: list[str]
    repository_root: str | None
    occurred_at: datetime
    fields: dict[str, Any]

    def to_json(self) -> dict[str, Any]:
        return {
            "hook_event_name": self.hook_event_name,
            "conversation_id": self.conversation_id,
            "generation_id": self.generation_id,
            "model": self.identity.model,
            "model_id": self.identity.model_id,
            "model_params": self.identity.model_params,
            "workspace_roots": self.workspace_roots,
            "repository_root": self.repository_root,
            "occurred_at": self.occurred_at.isoformat(),
            "fields": self.fields,
        }

    @staticmethod
    def from_json(payload: dict[str, Any]) -> ParsedEnvelope:
        return ParsedEnvelope(
            hook_event_name=payload["hook_event_name"],
            conversation_id=payload["conversation_id"],
            generation_id=payload.get("generation_id") or UNSCOPED_GENERATION_ID,
            identity=docs.ModelIdentity(
                model=payload.get("model"),
                model_id=payload.get("model_id"),
                model_params=payload.get("model_params") or [],
            ),
            workspace_roots=payload.get("workspace_roots") or [],
            repository_root=payload.get("repository_root"),
            occurred_at=to_utc(datetime.fromisoformat(payload["occurred_at"])),
            fields=payload.get("fields") or {},
        )


def _first_workspace_root(raw: dict[str, Any]) -> str | None:
    roots = raw.get("workspace_roots") or []
    if roots:
        return normalize_path(roots[0])
    cwd = raw.get("cwd")
    return normalize_path(cwd) if cwd else None


def parse_hook_payload(raw: dict[str, Any], config: RouterConfig) -> ParsedEnvelope | None:
    hook_event_name = raw.get("hook_event_name")
    if hook_event_name not in _HOOK_EVENT_TO_INTERNAL:
        return None

    conversation_id = raw.get("conversation_id")
    if not conversation_id:
        # App-lifecycle hooks (e.g. workspaceOpen) fire outside a conversation
        # and carry nothing this project can attribute a task to.
        return None

    identity = docs.ModelIdentity(
        model=raw.get("model"),
        model_id=raw.get("model_id"),
        model_params=raw.get("model_params") or [],
    )
    workspace_roots = [normalize_path(root) for root in (raw.get("workspace_roots") or [])]
    repository_root = _first_workspace_root(raw)

    max_prompt = config.redaction.max_prompt_chars
    max_tool_output = config.redaction.max_tool_output_chars

    fields: dict[str, Any] = {}

    if hook_event_name == "beforeSubmitPrompt":
        fields["prompt_preview"] = sanitize_free_text(raw.get("prompt"), max_prompt)

    elif hook_event_name in ("preToolUse", "postToolUse", "postToolUseFailure"):
        tool_input = raw.get("tool_input") or {}
        fields["tool_name"] = raw.get("tool_name")
        fields["tool_use_id"] = raw.get("tool_use_id")
        fields["command"] = sanitize_free_text(tool_input.get("command"), max_tool_output)
        fields["file_path"] = normalize_path(tool_input.get("file_path"))
        fields["duration_ms"] = raw.get("duration")
        if hook_event_name == "postToolUseFailure":
            fields["success"] = False
            fields["failure_type"] = raw.get("failure_type")
            fields["error_message"] = sanitize_free_text(raw.get("error_message"), max_tool_output)
        elif hook_event_name == "postToolUse":
            fields["success"] = True

    elif hook_event_name == "afterFileEdit":
        fields["file_path"] = normalize_path(raw.get("file_path"))
        fields["edit_count"] = len(raw.get("edits") or [])

    elif hook_event_name == "stop":
        fields["status"] = raw.get("status")
        fields["loop_count"] = raw.get("loop_count")

    elif hook_event_name == "sessionEnd":
        fields["reason"] = raw.get("reason")
        fields["duration_ms"] = raw.get("duration_ms")
        fields["final_status"] = raw.get("final_status")
        fields["error_message"] = sanitize_free_text(raw.get("error_message"), max_tool_output)

    return ParsedEnvelope(
        hook_event_name=hook_event_name,
        conversation_id=conversation_id,
        generation_id=raw.get("generation_id") or UNSCOPED_GENERATION_ID,
        identity=identity,
        workspace_roots=[root for root in workspace_roots if root],
        repository_root=repository_root,
        occurred_at=utc_now(),
        fields=fields,
    )


def apply_envelope(task_repo: TaskRepositorySync, envelope: ParsedEnvelope) -> None:
    task_id = task_repo.upsert_task(
        conversation_id=envelope.conversation_id,
        repository_root=envelope.repository_root,
        repository_commit=None,
        cursor_version=None,
        workspace_roots=envelope.workspace_roots,
        identity=envelope.identity,
        occurred_at=envelope.occurred_at,
    )

    # sessionStart/sessionEnd describe the whole conversation, not one
    # generation, so they never create or touch a task_generations record.
    if envelope.hook_event_name not in _CONVERSATION_ONLY_EVENTS:
        task_repo.upsert_generation(
            task_id=task_id,
            generation_id=envelope.generation_id,
            repository_root=envelope.repository_root,
            identity=envelope.identity,
            occurred_at=envelope.occurred_at,
        )

    internal_event_type = _HOOK_EVENT_TO_INTERNAL[envelope.hook_event_name]
    tool_use_id = envelope.fields.get("tool_use_id")
    if tool_use_id:
        # tool_use_id is stable per tool call across preToolUse/postToolUse/
        # postToolUseFailure retries, so it alone (plus the event type, since
        # the same tool_use_id appears at each phase) fully dedups the event.
        event_key = stable_event_key(envelope.conversation_id, internal_event_type, tool_use_id)
    else:
        # No caller-supplied unique id for this event type: dedup on the
        # combination of conversation, generation, and event-specific
        # identity fields. This can under-count repeated afterFileEdit calls
        # against the same file within one generation; accepted tradeoff
        # since Cursor does not provide a stable id for that event.
        event_key = stable_event_key(
            envelope.conversation_id,
            envelope.generation_id,
            internal_event_type,
            envelope.fields.get("file_path") or "",
        )
    event_document = docs.build_task_event(
        event_key=event_key,
        task_id=task_id,
        generation_id=envelope.generation_id,
        event_type=internal_event_type,
        occurred_at=envelope.occurred_at,
        tool_name=envelope.fields.get("tool_name"),
        command=envelope.fields.get("command"),
        file_path=envelope.fields.get("file_path"),
        success=envelope.fields.get("success"),
        duration_ms=envelope.fields.get("duration_ms"),
        metadata=envelope.fields,
    )
    task_repo.record_event(event_document)

    if envelope.hook_event_name == "beforeSubmitPrompt" and envelope.fields.get("prompt_preview"):
        task_repo.set_generation_prompt_preview(
            task_id=task_id,
            generation_id=envelope.generation_id,
            prompt_preview=envelope.fields["prompt_preview"],
            occurred_at=envelope.occurred_at,
        )

    if envelope.hook_event_name == "stop":
        # `stop` ends one generation/turn, not the whole conversation, so it
        # only ever updates that generation's status.
        status = _STOP_STATUS_MAP.get(envelope.fields.get("status"), TaskStatus.IN_PROGRESS)
        task_repo.set_generation_status(
            task_id=task_id,
            generation_id=envelope.generation_id,
            status=status,
            loop_count=envelope.fields.get("loop_count"),
            occurred_at=envelope.occurred_at,
        )

    if envelope.hook_event_name == "sessionEnd":
        reason = envelope.fields.get("reason")
        fallback_status = TaskStatus.COMPLETED if reason == "completed" else TaskStatus.ABORTED
        status = _STOP_STATUS_MAP.get(reason, fallback_status)
        task_repo.set_status(
            conversation_id=envelope.conversation_id,
            status=status,
            loop_count=None,
            occurred_at=envelope.occurred_at,
        )
