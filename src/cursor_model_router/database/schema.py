"""Schema initialization for cursor-model-router collections.

:func:`initialize_schema` applies validators, document migrations, and indexes
idempotently, which makes it safe to call via ``router db initialize`` on every
upgrade.
"""

from __future__ import annotations

from pymongo import ASCENDING, MongoClient
from pymongo.collection import Collection

from cursor_model_router.common.constants import CollectionNames
from cursor_model_router.database.migrations import run_document_migrations
from cursor_model_router.database.validators import apply_collection_validators

CURRENT_INDEX_REVISION = 7


def _ensure_indexes(
    collection: Collection, specs: list[tuple[list[tuple[str, int]], dict]]
) -> None:
    for keys, options in specs:
        collection.create_index(keys, **options)


def _drop_index_if_exists(collection: Collection, name: str) -> None:
    if name in collection.index_information():
        collection.drop_index(name)


def initialize_schema(client: MongoClient, database_name: str) -> None:
    db = client[database_name]

    # Validators must accept the new shapes while migrations rewrite existing
    # documents. Obsolete indexes are removed first because their old keys can
    # conflict while references are being changed.
    apply_collection_validators(db)
    _drop_index_if_exists(db[CollectionNames.TASK_EVENTS], "by_conversation_time")
    _drop_index_if_exists(
        db[CollectionNames.TASK_CLASSIFICATIONS], "uniq_conversation_classifier_source"
    )
    _drop_index_if_exists(
        db[CollectionNames.TASK_CLASSIFICATIONS], "uniq_task_classifier_source"
    )
    _drop_index_if_exists(db[CollectionNames.TASK_CLASSIFICATIONS], "uniq_task_source")
    _drop_index_if_exists(db[CollectionNames.VERIFICATION_RUNS], "by_conversation")
    _drop_index_if_exists(db[CollectionNames.VERIFICATION_RUNS], "uniq_idempotency_key")
    _drop_index_if_exists(db[CollectionNames.OUTCOME_SIGNALS], "by_conversation_signal")
    migrations_applied = run_document_migrations(db)

    _ensure_indexes(
        db[CollectionNames.TASKS],
        [
            (
                [("conversation_id", ASCENDING)],
                {"name": "uniq_conversation_id", "unique": True},
            ),
            (
                [("repository_root", ASCENDING), ("started_at", ASCENDING)],
                {"name": "by_repo_started"},
            ),
            ([("status", ASCENDING)], {"name": "by_status"}),
            (
                [("status", ASCENDING), ("finished_at", ASCENDING)],
                {"name": "by_status_finished"},
            ),
            (
                [("model_id", ASCENDING), ("started_at", ASCENDING)],
                {"name": "by_model_started"},
            ),
        ],
    )

    _ensure_indexes(
        db[CollectionNames.TASK_GENERATIONS],
        [
            (
                [("task_id", ASCENDING), ("generation_id", ASCENDING)],
                {"name": "uniq_task_generation", "unique": True},
            ),
            ([("status", ASCENDING)], {"name": "by_status"}),
        ],
    )

    _ensure_indexes(
        db[CollectionNames.TASK_EVENTS],
        [
            (
                [("task_id", ASCENDING), ("occurred_at", ASCENDING)],
                {"name": "by_task_time"},
            ),
            (
                [("task_id", ASCENDING), ("generation_id", ASCENDING), ("occurred_at", ASCENDING)],
                {"name": "by_task_generation_time"},
            ),
            ([("event_type", ASCENDING)], {"name": "by_event_type"}),
        ],
    )

    _ensure_indexes(
        db[CollectionNames.TASK_CLASSIFICATIONS],
        [
            (
                [("generation_task_id", ASCENDING), ("source", ASCENDING)],
                {"name": "uniq_generation_source", "unique": True},
            ),
            (
                [("task_id", ASCENDING)],
                {"name": "by_task"},
            ),
            (
                [("category", ASCENDING), ("primary_language", ASCENDING)],
                {"name": "by_category_language"},
            ),
            (
                [("model_id", ASCENDING), ("category", ASCENDING)],
                {"name": "by_model_category"},
            ),
            (
                [("repository_root", ASCENDING), ("category", ASCENDING)],
                {"name": "by_repo_category"},
            ),
        ],
    )

    _ensure_indexes(
        db[CollectionNames.VERIFICATION_DEFINITIONS],
        [
            (
                [("repository_root", ASCENDING), ("repo_config_hash", ASCENDING)],
                {"name": "uniq_repo_config", "unique": True},
            ),
        ],
    )

    _ensure_indexes(
        db[CollectionNames.VERIFICATION_RUNS],
        [
            ([("task_id", ASCENDING)], {"name": "by_task"}),
            (
                [("source", ASCENDING), ("task_id", ASCENDING)],
                {"name": "by_source_task"},
            ),
        ],
    )

    _ensure_indexes(
        db[CollectionNames.OUTCOME_SIGNALS],
        [
            (
                [("task_id", ASCENDING), ("signal_type", ASCENDING)],
                {"name": "by_task_signal"},
            ),
        ],
    )

    db[CollectionNames.SCHEMA_META].update_one(
        {"_id": "schema"},
        {
            "$set": {
                "index_revision": CURRENT_INDEX_REVISION,
                "migrations_applied_last_run": migrations_applied,
            }
        },
        upsert=True,
    )
