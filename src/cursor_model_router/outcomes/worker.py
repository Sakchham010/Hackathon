"""Asynchronous worker that derives weak outcome signals for finished tasks.

Companion to :mod:`cursor_model_router.classification.worker`: same polling
shape, run via ``router outcome extract-signals``. Conversation-level signals
are recorded once per conversation; generation-level signals are recorded
once per generation, keyed to that generation's own task id.
"""

from __future__ import annotations

from pymongo.asynchronous.database import AsyncDatabase

from cursor_model_router.common.constants import OutcomeSignalType
from cursor_model_router.common.ids import stable_event_key
from cursor_model_router.database.documents import build_outcome_signal
from cursor_model_router.database.repositories import OutcomeRepositoryAsync, TaskReaderAsync
from cursor_model_router.outcomes.signals import (
    OBSERVED_SOURCE,
    derive_conversation_signals,
    derive_generation_signals,
)


async def extract_signals_batch(database: AsyncDatabase, *, limit: int = 200) -> int:
    reader = TaskReaderAsync(database)
    outcomes = OutcomeRepositoryAsync(database)

    processed = 0
    async for task in reader.find_finished_tasks_without_outcome_signals(
        marker_signal_type=OutcomeSignalType.AGENT_STATUS, limit=limit
    ):
        task_id = task["_id"]
        events = await reader.find_events_for_task(task_id)

        for signal in derive_conversation_signals(task, events):
            signal_key = stable_event_key(task_id, signal.signal_type)
            document = build_outcome_signal(
                signal_key=signal_key,
                task_id=task_id,
                signal_type=signal.signal_type,
                source=OBSERVED_SOURCE,
                observed_at=signal.observed_at,
                payload=signal.payload,
            )
            await outcomes.record_signal(document)

        for generation in await reader.find_generations_for_task(task_id):
            generation_task_id = generation["_id"]
            generation_events = [
                event
                for event in events
                if event.get("generation_id") == generation["generation_id"]
            ]
            for signal in derive_generation_signals(generation_events):
                signal_key = stable_event_key(generation_task_id, signal.signal_type)
                document = build_outcome_signal(
                    signal_key=signal_key,
                    task_id=generation_task_id,
                    signal_type=signal.signal_type,
                    source=OBSERVED_SOURCE,
                    observed_at=signal.observed_at,
                    payload=signal.payload,
                )
                await outcomes.record_signal(document)

        processed += 1

    return processed
