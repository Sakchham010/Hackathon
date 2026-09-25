"""Repository layer: the only place that issues PyMongo calls.

Split into a synchronous side (used by the short-lived hook process) and an
asynchronous side (used by the long-running classification and verification
workers). Both build documents via :mod:`cursor_model_router.database.documents`
so the write shape is identical regardless of which client issued it, and
both are safe to call repeatedly with the same idempotency key.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import datetime
from typing import Any

from pymongo import ReturnDocument
from pymongo.asynchronous.database import AsyncDatabase
from pymongo.database import Database as SyncDatabase
from pymongo.errors import DuplicateKeyError

from cursor_model_router.common.constants import CollectionNames, TaskStatus
from cursor_model_router.common.ids import new_id
from cursor_model_router.database import documents as docs

_TERMINAL_STATUSES = [TaskStatus.COMPLETED, TaskStatus.ABORTED, TaskStatus.ERROR]


class TaskRepositorySync:
    """Used by the hook entry point. Every call must be fast and non-blocking."""

    def __init__(self, database: SyncDatabase) -> None:
        self._tasks = database[CollectionNames.TASKS]
        self._generations = database[CollectionNames.TASK_GENERATIONS]
        self._events = database[CollectionNames.TASK_EVENTS]

    def upsert_task(
        self,
        *,
        conversation_id: str,
        repository_root: str | None,
        repository_commit: str | None,
        cursor_version: str | None,
        workspace_roots: list[str],
        identity: docs.ModelIdentity,
        occurred_at: datetime,
    ) -> str:
        filter_, update = docs.build_task_upsert(
            task_id=new_id(),
            conversation_id=conversation_id,
            repository_root=repository_root,
            repository_commit=repository_commit,
            cursor_version=cursor_version,
            workspace_roots=workspace_roots,
            identity=identity,
            occurred_at=occurred_at,
        )
        try:
            task = self._tasks.find_one_and_update(
                filter_,
                update,
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # Concurrent first events can both attempt the upsert. The unique
            # conversation_id index chooses one task; resolve the winning GUID.
            task = self._tasks.find_one({"conversation_id": conversation_id})
        if task is None:
            raise RuntimeError(f"Task upsert did not return a document for {conversation_id}")
        return str(task["_id"])

    def upsert_generation(
        self,
        *,
        task_id: str,
        generation_id: str,
        repository_root: str | None,
        identity: docs.ModelIdentity,
        occurred_at: datetime,
    ) -> str:
        filter_, update = docs.build_generation_upsert(
            generation_task_id=new_id(),
            task_id=task_id,
            generation_id=generation_id,
            repository_root=repository_root,
            identity=identity,
            occurred_at=occurred_at,
        )
        try:
            generation = self._generations.find_one_and_update(
                filter_,
                update,
                upsert=True,
                return_document=ReturnDocument.AFTER,
            )
        except DuplicateKeyError:
            # Concurrent first events for the same generation can both attempt
            # the upsert; the unique (task_id, generation_id) index chooses one
            # winner, so resolve it the same way task upserts do.
            generation = self._generations.find_one(
                {"task_id": task_id, "generation_id": generation_id}
            )
        if generation is None:
            raise RuntimeError(
                f"Generation upsert did not return a document for {task_id}/{generation_id}"
            )
        return str(generation["_id"])

    def set_generation_prompt_preview(
        self, *, task_id: str, generation_id: str, prompt_preview: str, occurred_at: datetime
    ) -> None:
        filter_, update = docs.build_generation_prompt_update(
            task_id=task_id,
            generation_id=generation_id,
            prompt_preview=prompt_preview,
            occurred_at=occurred_at,
        )
        self._generations.update_one(filter_, update)

    def set_generation_status(
        self,
        *,
        task_id: str,
        generation_id: str,
        status: str,
        loop_count: int | None,
        occurred_at: datetime,
    ) -> None:
        filter_, update = docs.build_generation_status_update(
            task_id=task_id,
            generation_id=generation_id,
            status=status,
            loop_count=loop_count,
            occurred_at=occurred_at,
        )
        self._generations.update_one(filter_, update)

    def set_status(
        self, *, conversation_id: str, status: str, loop_count: int | None, occurred_at: datetime
    ) -> None:
        filter_, update = docs.build_task_status_update(
            conversation_id=conversation_id,
            status=status,
            loop_count=loop_count,
            occurred_at=occurred_at,
        )
        self._tasks.update_one(filter_, update)

    def record_event(self, event_document: dict[str, Any]) -> bool:
        """Insert an event, returning False if it already exists (idempotent)."""
        try:
            self._events.insert_one(event_document)
            return True
        except DuplicateKeyError:
            return False


class TaskReaderAsync:
    """Read-only task/event access for background workers."""

    def __init__(self, database: AsyncDatabase) -> None:
        self._tasks = database[CollectionNames.TASKS]
        self._generations = database[CollectionNames.TASK_GENERATIONS]
        self._events = database[CollectionNames.TASK_EVENTS]

    async def get_task(self, conversation_id: str) -> dict[str, Any] | None:
        return await self._tasks.find_one({"conversation_id": conversation_id})

    async def find_generations_for_task(self, task_id: str) -> list[dict[str, Any]]:
        cursor = self._generations.find({"task_id": task_id})
        return [generation async for generation in cursor]

    async def find_finished_generations_without_classification(
        self, *, limit: int
    ) -> AsyncIterator[dict[str, Any]]:
        """Yield generation tasks ready to classify.

        A generation is eligible once it has its own terminal status (set on
        ``stop``) or once its parent conversation has ended (``sessionEnd``)
        even if no explicit ``stop`` was observed for it. Classifying a
        generation is a one-time event: once classified, later activity in
        the same or a later generation never revisits it.
        """
        classifications = self._tasks.database[CollectionNames.TASK_CLASSIFICATIONS]
        classified_ids = {
            doc["generation_task_id"]
            async for doc in classifications.find({}, {"generation_task_id": 1})
        }
        finished_conversation_ids = {
            doc["_id"]
            async for doc in self._tasks.find(
                {"status": {"$in": _TERMINAL_STATUSES}}, {"_id": 1}
            )
        }
        cursor = self._generations.find(
            {
                "$or": [
                    {"status": {"$in": _TERMINAL_STATUSES}},
                    {"task_id": {"$in": list(finished_conversation_ids)}},
                ]
            }
        ).limit(limit)
        async for generation in cursor:
            if generation["_id"] not in classified_ids:
                yield generation

    async def find_events_for_task(self, task_id: str) -> list[dict[str, Any]]:
        cursor = self._events.find({"task_id": task_id}).sort("occurred_at", 1)
        return [event async for event in cursor]

    async def find_events_for_generation(
        self, *, task_id: str, generation_id: str
    ) -> list[dict[str, Any]]:
        cursor = self._events.find(
            {"task_id": task_id, "generation_id": generation_id}
        ).sort("occurred_at", 1)
        return [event async for event in cursor]

    async def find_finished_tasks_without_outcome_signals(
        self, *, marker_signal_type: str, limit: int
    ) -> AsyncIterator[dict[str, Any]]:
        signals = self._tasks.database[CollectionNames.OUTCOME_SIGNALS]
        signaled_ids = {
            doc["task_id"]
            async for doc in signals.find({"signal_type": marker_signal_type}, {"task_id": 1})
        }
        cursor = self._tasks.find({"status": {"$in": ["completed", "aborted", "error"]}}).limit(
            limit
        )
        async for task in cursor:
            if task["_id"] not in signaled_ids:
                yield task

    async def find_finished_tasks_needing_router_verification(
        self, *, limit: int
    ) -> AsyncIterator[dict[str, Any]]:
        runs = self._tasks.database[CollectionNames.VERIFICATION_RUNS]
        verified_ids = {
            doc["task_id"]
            async for doc in runs.find({"source": "router_verification"}, {"task_id": 1})
        }
        cursor = self._tasks.find({"status": {"$in": ["completed", "aborted", "error"]}}).limit(
            limit
        )
        async for task in cursor:
            if task["_id"] not in verified_ids:
                yield task


class ClassificationRepositoryAsync:
    def __init__(self, database: AsyncDatabase) -> None:
        self._classifications = database[CollectionNames.TASK_CLASSIFICATIONS]

    async def upsert_classification(self, document: dict[str, Any]) -> None:
        await self._classifications.update_one(
            {
                "generation_task_id": document["generation_task_id"],
                "source": document["source"],
            },
            {"$set": document},
            upsert=True,
        )

    async def find_for_generation(self, generation_task_id: str) -> list[dict[str, Any]]:
        cursor = self._classifications.find({"generation_task_id": generation_task_id})
        return [doc async for doc in cursor]

    async def find_for_conversation(self, task_id: str) -> list[dict[str, Any]]:
        cursor = self._classifications.find({"task_id": task_id})
        return [doc async for doc in cursor]


class OutcomeRepositoryAsync:
    def __init__(self, database: AsyncDatabase) -> None:
        self._signals = database[CollectionNames.OUTCOME_SIGNALS]

    async def record_signal(self, document: dict[str, Any]) -> bool:
        try:
            await self._signals.insert_one(document)
            return True
        except DuplicateKeyError:
            return False

    async def find_for_task(self, task_id: str) -> list[dict[str, Any]]:
        cursor = self._signals.find({"task_id": task_id})
        return [doc async for doc in cursor]


class VerificationRepositoryAsync:
    def __init__(self, database: AsyncDatabase) -> None:
        self._definitions = database[CollectionNames.VERIFICATION_DEFINITIONS]
        self._runs = database[CollectionNames.VERIFICATION_RUNS]

    async def upsert_definition(self, document: dict[str, Any]) -> dict[str, Any]:
        return await self._definitions.find_one_and_update(
            {
                "repository_root": document["repository_root"],
                "repo_config_hash": document["repo_config_hash"],
            },
            {"$set": document},
            upsert=True,
            return_document=ReturnDocument.AFTER,
        )

    async def record_run(self, document: dict[str, Any]) -> Any | None:
        try:
            result = await self._runs.insert_one(document)
            return result.inserted_id
        except DuplicateKeyError:
            return None

    async def update_run_result(
        self,
        *,
        run_id: Any,
        status: str,
        exit_code: int | None,
        duration_ms: int | None,
        finished_at: datetime,
        output_excerpt: str | None,
    ) -> None:
        await self._runs.update_one(
            {"_id": run_id},
            {
                "$set": {
                    "status": status,
                    "exit_code": exit_code,
                    "duration_ms": duration_ms,
                    "finished_at": finished_at,
                    "output_excerpt": output_excerpt,
                }
            },
        )

    async def find_for_task(self, task_id: str) -> list[dict[str, Any]]:
        cursor = self._runs.find({"task_id": task_id})
        return [doc async for doc in cursor]
