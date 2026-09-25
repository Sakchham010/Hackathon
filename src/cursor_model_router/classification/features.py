"""Pure feature extraction from a generation task and its recorded events.

No I/O and no Mongo imports: the worker fetches raw documents, this module
turns them into flat feature dicts, and :mod:`cursor_model_router.classification.rules`
turns features into a classification. Keeping this pure makes every feature
independently unit-testable against hand-built fixtures.

Two kinds of features are extracted, and they are never merged:

- :class:`PromptFeatures` comes only from the generation's own prompt text.
  It is the sole input to category/intent classification, since a request's
  intent is what the user asked for, not what happened while it was carried
  out.
- :class:`ActivityFeatures` comes only from the generation's own events
  (edits, tool calls, commands, failures). It describes observed activity
  and outcomes, and is evidence about *how* a generation went, not *what*
  was asked for.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any

from cursor_model_router.classification.taxonomy import (
    BUILD_COMMAND_KEYWORDS,
    EXTENSION_LANGUAGE_MAP,
    STACK_TRACE_KEYWORDS,
    TEST_COMMAND_KEYWORDS,
)
from cursor_model_router.common.constants import HookEventType


@dataclass(frozen=True)
class PromptFeatures:
    prompt_text: str
    prompt_length: int


@dataclass(frozen=True)
class ActivityFeatures:
    touched_files: list[str] = field(default_factory=list)
    touched_extensions: Counter = field(default_factory=Counter)
    languages: Counter = field(default_factory=Counter)
    unique_directories: int = 0
    edit_count: int = 0
    tool_call_count: int = 0
    shell_command_count: int = 0
    commands: list[str] = field(default_factory=list)
    had_tool_failure: bool = False
    failure_count: int = 0
    saw_build_command: bool = False
    saw_test_command: bool = False
    saw_stack_trace: bool = False
    loop_count: int = 0


def _matches_any(text: str, keywords: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(keyword in lowered for keyword in keywords)


def extract_prompt_features(generation: dict[str, Any]) -> PromptFeatures:
    """Build intent features from a generation's own prompt only.

    ``generation`` is a ``task_generations`` document; its ``prompt_preview``
    reflects exactly the one prompt this classification is about, never a
    different turn in the same conversation.
    """
    prompt_text = generation.get("prompt_preview") or ""
    return PromptFeatures(prompt_text=prompt_text, prompt_length=len(prompt_text))


def extract_activity_features(events: list[dict[str, Any]]) -> ActivityFeatures:
    """Build activity/outcome features from a set of events.

    Callers are responsible for scoping ``events`` to the window they want
    described (one generation, or an entire conversation for aggregate
    reporting) -- this function draws no distinction and never looks at
    prompt text.
    """
    touched_files: list[str] = []
    extensions: Counter = Counter()
    languages: Counter = Counter()
    directories: set[str] = set()
    edit_count = 0
    seen_tool_use_ids: set[str] = set()
    tool_call_count = 0
    shell_command_count = 0
    commands: list[str] = []
    had_tool_failure = False
    failure_count = 0
    saw_build_command = False
    saw_test_command = False
    saw_stack_trace = False
    loop_count = 0

    for event in events:
        event_type = event.get("event_type")
        file_path = event.get("file_path")
        command = event.get("command")
        metadata = event.get("metadata") or {}

        # Only edits change what was actually touched; tool reads (e.g. a
        # file opened via pre_tool_use) are not scope/language evidence.
        if event_type == HookEventType.AFTER_FILE_EDIT and file_path:
            touched_files.append(file_path)
            suffix = PurePosixPath(file_path).suffix.lower()
            if suffix:
                extensions[suffix] += 1
                language = EXTENSION_LANGUAGE_MAP.get(suffix)
                if language:
                    languages[language] += 1
            directories.add(str(PurePosixPath(file_path).parent))
            edit_count += metadata.get("edit_count") or 1

        if event_type in (
            HookEventType.PRE_TOOL_USE,
            HookEventType.POST_TOOL_USE,
            HookEventType.POST_TOOL_USE_FAILURE,
        ):
            # Count one logical call per tool_use_id so retries and the
            # pre/post/failure phases of a single call are never double
            # counted; anonymous calls (no id) each count once.
            tool_use_id = metadata.get("tool_use_id")
            if tool_use_id:
                if tool_use_id not in seen_tool_use_ids:
                    seen_tool_use_ids.add(tool_use_id)
                    tool_call_count += 1
            else:
                tool_call_count += 1

        if command:
            commands.append(command)
            shell_command_count += 1
            if _matches_any(command, BUILD_COMMAND_KEYWORDS):
                saw_build_command = True
            if _matches_any(command, TEST_COMMAND_KEYWORDS):
                saw_test_command = True

        if event_type == HookEventType.POST_TOOL_USE_FAILURE:
            had_tool_failure = True
            failure_count += 1
            error_message = metadata.get("error_message") or ""
            if _matches_any(error_message, STACK_TRACE_KEYWORDS):
                saw_stack_trace = True

        if event_type == HookEventType.STOP:
            loop_count = max(loop_count, metadata.get("loop_count") or 0)

    return ActivityFeatures(
        touched_files=touched_files,
        touched_extensions=extensions,
        languages=languages,
        unique_directories=len(directories),
        edit_count=edit_count,
        tool_call_count=tool_call_count,
        shell_command_count=shell_command_count,
        commands=commands,
        had_tool_failure=had_tool_failure,
        failure_count=failure_count,
        saw_build_command=saw_build_command,
        saw_test_command=saw_test_command,
        saw_stack_trace=saw_stack_trace,
        loop_count=loop_count,
    )
