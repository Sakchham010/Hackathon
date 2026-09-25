"""Read models for the review console.

The UI gets a deliberately small, joined view of MongoDB. Raw tool output and
the complete event stream stay server-side; the API exposes bounded activity
summaries instead.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime
from pathlib import Path
from typing import Any

from bson import ObjectId
from pymongo.database import Database

from cursor_model_router.common.config import RouterConfig
from cursor_model_router.common.constants import CollectionNames, HookEventType, TaskStatus
from cursor_model_router.verification.trust import find_trust_entry

TERMINAL_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.ABORTED,
    TaskStatus.ERROR,
}


def json_safe(value: Any) -> Any:
    """Convert BSON/Python values into values accepted by JSON responses."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, ObjectId):
        return str(value)
    if isinstance(value, dict):
        return {str(key): json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    return value


def _task_id(task: dict[str, Any]) -> str:
    return str(task["_id"])


def _distinct_strings(values: list[str | None]) -> list[str]:
    return list(dict.fromkeys(value for value in values if value))


class ReviewQueries:
    def __init__(self, database: Database, config: RouterConfig | None = None) -> None:
        self.database = database
        self.config = config

    def resolve_task(self, identifier: str) -> dict[str, Any] | None:
        task = self.database[CollectionNames.TASKS].find_one({"_id": identifier})
        if task is None:
            task = self.database[CollectionNames.TASKS].find_one({"conversation_id": identifier})
        return task

    def _runs(self, task_id: str) -> list[dict[str, Any]]:
        return list(
            self.database[CollectionNames.VERIFICATION_RUNS]
            .find({"task_id": task_id})
            .sort("started_at", 1)
        )

    def _generations(self, task_id: str) -> list[dict[str, Any]]:
        return list(
            self.database[CollectionNames.TASK_GENERATIONS]
            .find({"task_id": task_id})
            .sort("started_at", 1)
        )

    def _classifications(self, task_id: str) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in self.database[CollectionNames.TASK_CLASSIFICATIONS].find(
            {"task_id": task_id}
        ):
            grouped.setdefault(str(row["generation_task_id"]), []).append(row)
        return grouped

    def _signals(self, key: str) -> list[dict[str, Any]]:
        return list(
            self.database[CollectionNames.OUTCOME_SIGNALS]
            .find({"task_id": key})
            .sort("observed_at", 1)
        )

    def _summary(self, task: dict[str, Any]) -> dict[str, Any]:
        task_id = _task_id(task)
        generations = self._generations(task_id)
        classifications = self._classifications(task_id)
        runs = self._runs(task_id)
        models = _distinct_strings(
            [task.get("model"), task.get("model_id")]
            + [generation.get("model") or generation.get("model_id") for generation in generations]
        )
        categories = _distinct_strings(
            [
                classification.get("category")
                for rows in classifications.values()
                for classification in rows
            ]
        )
        router_checks = Counter(
            run.get("status")
            for run in runs
            if run.get("source") == "router_verification" and run.get("status")
        )
        human_evidence_count = sum(run.get("source") == "user_submitted" for run in runs)
        return {
            "task_id": task_id,
            "conversation_id": str(task["conversation_id"]),
            "status": task.get("status"),
            "repository_root": task.get("repository_root"),
            "prompt_preview": generations[0].get("prompt_preview") if generations else None,
            "models": models,
            "categories": categories,
            "router_checks": dict(router_checks),
            "human_evidence_count": human_evidence_count,
            "needs_review": task.get("status") in TERMINAL_STATUSES and human_evidence_count == 0,
            "started_at": task.get("started_at"),
            "updated_at": task.get("updated_at"),
            "finished_at": task.get("finished_at"),
        }

    def list_conversations(
        self, *, filter_name: str = "needs_review", limit: int = 100
    ) -> list[dict[str, Any]]:
        tasks = self.database[CollectionNames.TASKS].find({}).sort(
            [("updated_at", -1), ("started_at", -1)]
        ).limit(limit)
        summaries = [self._summary(task) for task in tasks]
        if filter_name == "needs_review":
            return [summary for summary in summaries if summary["needs_review"]]
        if filter_name == "in_progress":
            return [summary for summary in summaries if summary["status"] == TaskStatus.IN_PROGRESS]
        if filter_name == "has_human_evidence":
            return [summary for summary in summaries if summary["human_evidence_count"] > 0]
        return summaries

    def _activity_summary(
        self, events: list[dict[str, Any]], repository_root: str | None
    ) -> dict[str, Any]:
        # Match classification: only after_file_edit counts as an edit.
        # Tool reads (pre/post_tool_use with a file_path) are not edited files.
        # Cursor sometimes fires afterFileEdit with the workspace directory
        # itself as file_path; relative_to() turns that into ".", which is
        # not a file.
        edited_files = _distinct_strings(
            [
                event.get("file_path")
                for event in events
                if event.get("event_type") == HookEventType.AFTER_FILE_EDIT
                and event.get("file_path")
                and not self._is_repository_root_path(
                    event["file_path"], repository_root
                )
            ]
        )
        commands = _distinct_strings(
            [event.get("command") for event in events if event.get("command")]
        )
        failures = sum(
            event.get("event_type") == "post_tool_use_failure" or event.get("success") is False
            for event in events
        )
        return {
            "event_count": len(events),
            "edited_files": edited_files[:100],
            "commands": commands[:50],
            "tool_failures": failures,
            "event_types": dict(Counter(event.get("event_type") for event in events)),
            "repository_relative_files": [
                self._relative_path(path, repository_root) for path in edited_files[:100]
            ],
        }

    @staticmethod
    def _is_repository_root_path(path: str, repository_root: str | None) -> bool:
        if path in {".", "./"}:
            return True
        if not repository_root:
            return False
        try:
            relative = Path(path).resolve().relative_to(Path(repository_root).resolve())
        except (ValueError, OSError):
            return False
        return str(relative) in {".", ""}

    @staticmethod
    def _relative_path(path: str, repository_root: str | None) -> str:
        if not repository_root:
            return path
        try:
            return str(Path(path).resolve().relative_to(Path(repository_root).resolve()))
        except (ValueError, OSError):
            return path

    def get_conversation(self, identifier: str) -> dict[str, Any] | None:
        task = self.resolve_task(identifier)
        if task is None:
            return None
        task_id = _task_id(task)
        classifications = self._classifications(task_id)
        generations = []
        for generation in self._generations(task_id):
            generation_id = str(generation["_id"])
            events = list(
                self.database[CollectionNames.TASK_EVENTS]
                .find(
                    {
                        "task_id": task_id,
                        "generation_id": generation.get("generation_id"),
                    }
                )
                .sort("occurred_at", 1)
            )
            activity = self._activity_summary(events, task.get("repository_root"))
            generations.append(
                {
                    "generation_task_id": generation_id,
                    "generation_id": generation.get("generation_id"),
                    "prompt_preview": generation.get("prompt_preview"),
                    "model": generation.get("model"),
                    "model_id": generation.get("model_id"),
                    "status": generation.get("status"),
                    "started_at": generation.get("started_at"),
                    "finished_at": generation.get("finished_at"),
                    "classifications": classifications.get(generation_id, []),
                    "outcome_signals": self._signals(generation_id),
                    "activity": activity,
                }
            )
        return {
            "task_id": task_id,
            "conversation_id": str(task["conversation_id"]),
            "task": task,
            "generations": generations,
            "outcome_signals": self._signals(task_id),
            "verification_runs": self._runs(task_id),
            "verification_trusted": bool(
                self.config
                and task.get("repository_root")
                and find_trust_entry(
                    task["repository_root"],
                    self.config.verification.trusted_repositories,
                )
            ),
        }
