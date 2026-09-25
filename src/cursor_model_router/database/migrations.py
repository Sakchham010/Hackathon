"""Schema-versioned document migrations for cursor-model-router.

Unlike relational migrations, these are small, idempotent Python functions
that transform existing documents when a new ``DOCUMENT_REVISION`` ships.
``router db initialize`` applies validators, runs pending migrations, and then
creates indexes for the migrated shape.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pymongo.database import Database

from cursor_model_router.common.constants import (
    CollectionNames,
    OutcomeSource,
    VerificationCheckType,
    VerificationMethod,
)
from cursor_model_router.common.ids import new_id
from cursor_model_router.common.time_utils import utc_now
from cursor_model_router.database.documents import SCHEMA_VERSION

DOCUMENT_REVISION_META_ID = "document_revisions"
CURRENT_DOCUMENT_REVISION = 5

MigrationFn = Callable[[Database], None]


def _noop(_database: Database) -> None:
    """Baseline revision; no document transforms yet."""


def _migrate_task_guids(database: Database) -> None:
    """Give legacy tasks GUID keys and point their events at those keys."""
    tasks = database[CollectionNames.TASKS]
    events = database[CollectionNames.TASK_EVENTS]

    for legacy_task in tasks.find({"conversation_id": {"$exists": False}}):
        conversation_id = str(legacy_task["_id"])
        migrated_task = tasks.find_one({"conversation_id": conversation_id})

        if migrated_task is None:
            task_id = new_id()
            migrated_task = dict(legacy_task)
            migrated_task["_id"] = task_id
            migrated_task["conversation_id"] = conversation_id
            migrated_task["schema_version"] = SCHEMA_VERSION
            tasks.insert_one(migrated_task)
        else:
            task_id = str(migrated_task["_id"])

        events.update_many(
            {"conversation_id": conversation_id},
            {
                "$set": {"task_id": task_id, "schema_version": SCHEMA_VERSION},
                "$unset": {"conversation_id": ""},
            },
        )
        tasks.delete_one({"_id": legacy_task["_id"]})

    # Complete event rewrites if a prior migration run was interrupted after
    # creating the replacement task.
    for task in tasks.find({"conversation_id": {"$exists": True}}):
        events.update_many(
            {"conversation_id": task["conversation_id"]},
            {
                "$set": {"task_id": str(task["_id"]), "schema_version": SCHEMA_VERSION},
                "$unset": {"conversation_id": ""},
            },
        )


def _migrate_child_task_references(database: Database) -> None:
    """Replace remaining conversation references with task GUID references."""
    tasks = database[CollectionNames.TASKS]
    child_collections = (
        database[CollectionNames.TASK_CLASSIFICATIONS],
        database[CollectionNames.OUTCOME_SIGNALS],
        database[CollectionNames.VERIFICATION_RUNS],
    )

    for collection in child_collections:
        for document in collection.find({"conversation_id": {"$exists": True}}):
            conversation_id = str(document["conversation_id"])
            task = tasks.find_one({"conversation_id": conversation_id})
            if task is None:
                # User-submitted verification records historically could be
                # stored before their task was collected. Preserve those rows
                # by creating the minimal task they now need to reference.
                started_at = (
                    document.get("created_at")
                    or document.get("observed_at")
                    or document.get("started_at")
                    or utc_now()
                )
                task_id = new_id()
                tasks.insert_one(
                    {
                        "_id": task_id,
                        "conversation_id": conversation_id,
                        "started_at": started_at,
                        "updated_at": started_at,
                        "schema_version": SCHEMA_VERSION,
                    }
                )
            else:
                task_id = str(task["_id"])

            collection.update_one(
                {"_id": document["_id"]},
                {
                    "$set": {"task_id": task_id, "schema_version": SCHEMA_VERSION},
                    "$unset": {"conversation_id": ""},
                },
            )


def _migrate_lean_verification_runs(database: Database) -> None:
    """Remove fields no longer part of the verification-run contract."""
    database[CollectionNames.VERIFICATION_RUNS].update_many(
        {},
        {
            "$set": {"schema_version": SCHEMA_VERSION},
            "$unset": {
                "idempotency_key": "",
                "definition_id": "",
                "check_name": "",
            },
        },
    )


def _migrate_verification_labels(database: Database) -> None:
    """Add method and check type to existing task-level verification records."""
    runs = database[CollectionNames.VERIFICATION_RUNS]
    runs.update_many(
        {"source": OutcomeSource.ROUTER_VERIFICATION},
        {
            "$set": {
                "verification_method": VerificationMethod.AUTOMATED,
                "check_type": VerificationCheckType.OTHER,
                "schema_version": SCHEMA_VERSION,
            }
        },
    )
    runs.update_many(
        {"source": {"$ne": OutcomeSource.ROUTER_VERIFICATION}},
        {
            "$set": {
                "verification_method": VerificationMethod.MANUAL,
                "check_type": VerificationCheckType.OTHER,
                "schema_version": SCHEMA_VERSION,
            }
        },
    )


MIGRATIONS: list[tuple[int, int, MigrationFn]] = [
    (0, 1, _noop),
    (1, 2, _migrate_task_guids),
    (2, 3, _migrate_child_task_references),
    (3, 4, _migrate_lean_verification_runs),
    (4, 5, _migrate_verification_labels),
]


def _read_revision(database: Database) -> int:
    meta = database[CollectionNames.SCHEMA_META].find_one({"_id": DOCUMENT_REVISION_META_ID})
    if meta is None:
        return 0
    return int(meta.get("revision", 0))


def run_document_migrations(database: Database) -> int:
    """Apply pending migrations. Returns the number of migrations executed."""
    current = _read_revision(database)
    applied = 0

    for from_revision, to_revision, migrate in MIGRATIONS:
        if current != from_revision:
            continue
        migrate(database)
        current = to_revision
        applied += 1

    database[CollectionNames.SCHEMA_META].update_one(
        {"_id": DOCUMENT_REVISION_META_ID},
        {"$set": {"revision": current}},
        upsert=True,
    )
    return applied


def migration_plan(database: Database) -> list[dict[str, Any]]:
    """Describe pending migrations without applying them (for diagnostics)."""
    current = _read_revision(database)
    pending: list[dict[str, Any]] = []
    for from_revision, to_revision, migrate in MIGRATIONS:
        if current != from_revision:
            continue
        pending.append(
            {
                "from_revision": from_revision,
                "to_revision": to_revision,
                "callable": migrate.__name__,
            }
        )
        current = to_revision
    return pending
