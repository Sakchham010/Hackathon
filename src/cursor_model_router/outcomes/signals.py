"""Derive weak, non-authoritative outcome signals from observed activity.

None of these signals are a success/failure label. They are evidence that
later analysis (or a human) can weigh alongside router-executed and
user-submitted verification results.

Two scopes are kept separate, mirroring the classification split between
intent and activity:

- Conversation-level signals (``agent_status``, ``follow_up_generation``)
  describe the whole session and are keyed to the conversation task.
- Generation-level signals (``tool_failure``, ``shell_exit``,
  ``build_test_activity``) describe one generation's own activity and are
  keyed to that generation's task id, so a busy later turn never gets
  blended into an earlier turn's outcome evidence.

Each signal is produced exactly once per (task, signal_type), keyed
deterministically so re-running the worker is a no-op.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from cursor_model_router.classification.features import extract_activity_features
from cursor_model_router.common.constants import OutcomeSignalType, OutcomeSource
from cursor_model_router.common.time_utils import utc_now


@dataclass(frozen=True)
class DerivedSignal:
    signal_type: str
    payload: dict[str, Any]
    observed_at: datetime


def derive_conversation_signals(
    task: dict[str, Any], events: list[dict[str, Any]]
) -> list[DerivedSignal]:
    """Conversation-wide signals: overall status and whether follow-up turns occurred."""
    observed_at = utc_now()
    signals: list[DerivedSignal] = []
    activity = extract_activity_features(events)

    generation_ids = {
        event.get("generation_id") for event in events if event.get("generation_id")
    }

    signals.append(
        DerivedSignal(
            signal_type=OutcomeSignalType.AGENT_STATUS,
            payload={
                "status": task.get("status"),
                "loop_count": activity.loop_count,
                "started_at": task.get("started_at"),
                "finished_at": task.get("finished_at"),
            },
            observed_at=observed_at,
        )
    )

    if len(generation_ids) > 1:
        signals.append(
            DerivedSignal(
                signal_type=OutcomeSignalType.FOLLOW_UP_GENERATION,
                payload={"generation_count": len(generation_ids)},
                observed_at=observed_at,
            )
        )

    return signals


def derive_generation_signals(events: list[dict[str, Any]]) -> list[DerivedSignal]:
    """Signals scoped to one generation's own events: failures and activity observed."""
    observed_at = utc_now()
    signals: list[DerivedSignal] = []
    activity = extract_activity_features(events)

    tool_failures = [
        event for event in events if event.get("event_type") == "post_tool_use_failure"
    ]

    if tool_failures:
        signals.append(
            DerivedSignal(
                signal_type=OutcomeSignalType.TOOL_FAILURE,
                payload={
                    "failure_count": len(tool_failures),
                    "failure_types": sorted(
                        {
                            f.get("metadata", {}).get("failure_type")
                            for f in tool_failures
                            if f.get("metadata")
                        }
                    ),
                },
                observed_at=observed_at,
            )
        )

    if activity.shell_command_count:
        signals.append(
            DerivedSignal(
                signal_type=OutcomeSignalType.SHELL_EXIT,
                payload={
                    "shell_command_count": activity.shell_command_count,
                    "had_failure": activity.had_tool_failure,
                },
                observed_at=observed_at,
            )
        )

    if activity.saw_build_command or activity.saw_test_command:
        signals.append(
            DerivedSignal(
                signal_type=OutcomeSignalType.BUILD_TEST_ACTIVITY,
                payload={
                    "saw_build_command": activity.saw_build_command,
                    "saw_test_command": activity.saw_test_command,
                },
                observed_at=observed_at,
            )
        )

    return signals


OBSERVED_SOURCE = OutcomeSource.OBSERVED
