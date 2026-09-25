"""Unit tests for schema initialization helpers."""

from __future__ import annotations

import mongomock

from cursor_model_router.common.constants import CollectionNames
from cursor_model_router.database.documents import SCHEMA_VERSION
from cursor_model_router.database.migrations import (
    CURRENT_DOCUMENT_REVISION,
    DOCUMENT_REVISION_META_ID,
    MIGRATIONS,
    run_document_migrations,
)
from cursor_model_router.database.validators import COLLECTION_VALIDATORS


def test_collection_validators_cover_all_data_collections():
    expected = {
        CollectionNames.TASKS,
        CollectionNames.TASK_GENERATIONS,
        CollectionNames.TASK_EVENTS,
        CollectionNames.TASK_CLASSIFICATIONS,
        CollectionNames.VERIFICATION_DEFINITIONS,
        CollectionNames.VERIFICATION_RUNS,
        CollectionNames.OUTCOME_SIGNALS,
    }
    assert set(COLLECTION_VALIDATORS) == expected


def test_run_document_migrations_is_idempotent():
    database = mongomock.MongoClient()["cursor_model_router_test"]

    applied_first = run_document_migrations(database)
    applied_second = run_document_migrations(database)

    assert applied_first == len(MIGRATIONS)
    assert applied_second == 0
    meta = database[CollectionNames.SCHEMA_META].find_one({"_id": DOCUMENT_REVISION_META_ID})
    assert meta["revision"] == CURRENT_DOCUMENT_REVISION


def test_verification_run_migration_removes_legacy_identity_fields():
    database = mongomock.MongoClient()["cursor_model_router_test"]
    database[CollectionNames.VERIFICATION_RUNS].insert_one(
        {
            "task_id": "task-1",
            "idempotency_key": "legacy-key",
            "definition_id": "legacy-definition",
            "check_name": "legacy-check",
            "status": "passed",
            "started_at": mongomock.utcnow(),
            "source": "router_verification",
            "schema_version": 3,
        }
    )

    run_document_migrations(database)

    run = database[CollectionNames.VERIFICATION_RUNS].find_one({"task_id": "task-1"})
    assert run is not None
    assert run["schema_version"] == SCHEMA_VERSION
    assert "idempotency_key" not in run
    assert "definition_id" not in run
    assert "check_name" not in run
    assert run["verification_method"] == "automated"
    assert run["check_type"] == "other"


def test_task_guid_migration_rekeys_tasks_and_references_events():
    database = mongomock.MongoClient()["cursor_model_router_test"]
    database[CollectionNames.TASKS].insert_one(
        {
            "_id": "conv-legacy",
            "started_at": mongomock.utcnow(),
            "schema_version": 1,
        }
    )
    database[CollectionNames.TASK_EVENTS].insert_one(
        {
            "_id": "event-legacy",
            "conversation_id": "conv-legacy",
            "event_type": "session_start",
            "occurred_at": mongomock.utcnow(),
            "schema_version": 1,
        }
    )
    classification_id = (
        database[CollectionNames.TASK_CLASSIFICATIONS]
        .insert_one(
            {
                "conversation_id": "conv-legacy",
                "classifier_version": "rules-v1",
                "source": "rules",
                "schema_version": 1,
            }
        )
        .inserted_id
    )
    signal_id = (
        database[CollectionNames.OUTCOME_SIGNALS]
        .insert_one(
            {
                "_id": "signal-legacy",
                "conversation_id": "conv-legacy",
                "signal_type": "agent_status",
                "schema_version": 1,
            }
        )
        .inserted_id
    )
    run_id = (
        database[CollectionNames.VERIFICATION_RUNS]
        .insert_one(
            {
                "conversation_id": "conv-legacy",
                "idempotency_key": "run-legacy",
                "schema_version": 1,
            }
        )
        .inserted_id
    )

    run_document_migrations(database)

    task = database[CollectionNames.TASKS].find_one({"conversation_id": "conv-legacy"})
    assert task is not None
    assert task["_id"] != "conv-legacy"
    assert task["schema_version"] == SCHEMA_VERSION
    assert database[CollectionNames.TASKS].find_one({"_id": "conv-legacy"}) is None

    event = database[CollectionNames.TASK_EVENTS].find_one({"_id": "event-legacy"})
    assert event["task_id"] == task["_id"]
    assert event["schema_version"] == SCHEMA_VERSION
    assert "conversation_id" not in event

    for collection_name, document_id in (
        (CollectionNames.TASK_CLASSIFICATIONS, classification_id),
        (CollectionNames.OUTCOME_SIGNALS, signal_id),
        (CollectionNames.VERIFICATION_RUNS, run_id),
    ):
        child = database[collection_name].find_one({"_id": document_id})
        assert child["task_id"] == task["_id"]
        assert child["schema_version"] == SCHEMA_VERSION
        assert "conversation_id" not in child


def test_child_reference_migration_preserves_orphaned_verification_runs():
    database = mongomock.MongoClient()["cursor_model_router_test"]
    run_id = (
        database[CollectionNames.VERIFICATION_RUNS]
        .insert_one(
            {
                "conversation_id": "conv-orphaned",
                "idempotency_key": "run-orphaned",
                "started_at": mongomock.utcnow(),
                "schema_version": 2,
            }
        )
        .inserted_id
    )

    run_document_migrations(database)

    task = database[CollectionNames.TASKS].find_one({"conversation_id": "conv-orphaned"})
    run = database[CollectionNames.VERIFICATION_RUNS].find_one({"_id": run_id})
    assert task is not None
    assert run["task_id"] == task["_id"]
    assert "conversation_id" not in run
