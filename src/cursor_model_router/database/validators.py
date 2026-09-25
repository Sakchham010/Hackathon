"""MongoDB JSON Schema validators for cursor-model-router collections.

Validators are applied with ``validationLevel: moderate`` so existing
documents that predate a schema change keep working while new writes are
checked. Schemas intentionally allow ``additionalProperties`` so optional
fields can evolve without a validator bump for every new attribute.
"""

from __future__ import annotations

from typing import Any

from cursor_model_router.common.constants import CollectionNames

_VALIDATION_OPTIONS = {"validationLevel": "moderate", "validationAction": "error"}


def _with_schema_version(required: list[str]) -> dict[str, Any]:
    return {
        "bsonType": "object",
        "required": required,
        "additionalProperties": True,
        "properties": {
            "schema_version": {"bsonType": "int"},
        },
    }


_TASK_GENERATION_REQUIRED = [
    "_id",
    "task_id",
    "generation_id",
    "started_at",
    "status",
    "schema_version",
]
_TASK_EVENT_REQUIRED = [
    "_id",
    "task_id",
    "generation_id",
    "event_type",
    "occurred_at",
    "schema_version",
]
_VERIFICATION_DEFINITION_REQUIRED = [
    "repository_root",
    "repo_config_hash",
    "checks",
    "trusted",
    "loaded_at",
    "schema_version",
]
_VERIFICATION_RUN_REQUIRED = [
    "task_id",
    "verification_method",
    "check_type",
    "status",
    "started_at",
    "source",
    "schema_version",
]
_OUTCOME_SIGNAL_REQUIRED = [
    "_id",
    "task_id",
    "signal_type",
    "source",
    "observed_at",
    "payload",
    "schema_version",
]


COLLECTION_VALIDATORS: dict[str, dict[str, Any]] = {
    CollectionNames.TASKS: {
        **_with_schema_version(["_id", "conversation_id", "started_at", "schema_version"]),
        "properties": {
            **_with_schema_version(["_id", "conversation_id", "started_at", "schema_version"])[
                "properties"
            ],
            "_id": {"bsonType": "string"},
            "conversation_id": {"bsonType": "string"},
            "started_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
            "finished_at": {"bsonType": "date"},
            "repository_root": {"bsonType": ["string", "null"]},
            "repository_commit": {"bsonType": ["string", "null"]},
            "status": {"bsonType": "string"},
            "model": {"bsonType": ["string", "null"]},
            "model_id": {"bsonType": ["string", "null"]},
            "workspace_roots": {"bsonType": "array"},
        },
    },
    CollectionNames.TASK_GENERATIONS: {
        **_with_schema_version(_TASK_GENERATION_REQUIRED),
        "properties": {
            **_with_schema_version(_TASK_GENERATION_REQUIRED)["properties"],
            "_id": {"bsonType": "string"},
            "task_id": {"bsonType": "string"},
            "generation_id": {"bsonType": "string"},
            "started_at": {"bsonType": "date"},
            "updated_at": {"bsonType": "date"},
            "finished_at": {"bsonType": ["date", "null"]},
            "repository_root": {"bsonType": ["string", "null"]},
            "model": {"bsonType": ["string", "null"]},
            "model_id": {"bsonType": ["string", "null"]},
            "prompt_preview": {"bsonType": "string"},
            "status": {"bsonType": "string"},
            "loop_count": {"bsonType": ["int", "long", "null"]},
        },
    },
    CollectionNames.TASK_EVENTS: {
        **_with_schema_version(_TASK_EVENT_REQUIRED),
        "properties": {
            **_with_schema_version(_TASK_EVENT_REQUIRED)["properties"],
            "_id": {"bsonType": "string"},
            "task_id": {"bsonType": "string"},
            "generation_id": {"bsonType": "string"},
            "event_type": {"bsonType": "string"},
            "occurred_at": {"bsonType": "date"},
            "tool_name": {"bsonType": ["string", "null"]},
            "command": {"bsonType": ["string", "null"]},
            "file_path": {"bsonType": ["string", "null"]},
            "success": {"bsonType": ["bool", "null"]},
            "duration_ms": {"bsonType": ["int", "long", "null"]},
            "metadata": {"bsonType": "object"},
        },
    },
    CollectionNames.TASK_CLASSIFICATIONS: {
        **_with_schema_version(
            [
                "task_id",
                "generation_task_id",
                "source",
                "category",
                "confidence",
                "created_at",
                "schema_version",
            ]
        ),
        "properties": {
            **_with_schema_version(
                [
                    "task_id",
                    "generation_task_id",
                    "source",
                    "category",
                    "confidence",
                    "created_at",
                    "schema_version",
                ]
            )["properties"],
            "task_id": {"bsonType": "string"},
            "generation_task_id": {"bsonType": "string"},
            "source": {"bsonType": "string"},
            "category": {"bsonType": "string"},
            "subcategory": {"bsonType": ["string", "null"]},
            "primary_language": {"bsonType": ["string", "null"]},
            "intent": {"bsonType": ["string", "null"]},
            "cross_file_scope": {"bsonType": ["bool", "null"]},
            "complexity": {"bsonType": ["string", "null"]},
            "confidence": {"bsonType": ["double", "int"]},
            "evidence": {"bsonType": "object"},
            "model": {"bsonType": ["string", "null"]},
            "model_id": {"bsonType": ["string", "null"]},
            "repository_root": {"bsonType": ["string", "null"]},
            "provider": {"bsonType": ["string", "null"]},
            "provider_model": {"bsonType": ["string", "null"]},
            "prompt_version": {"bsonType": ["string", "null"]},
            "created_at": {"bsonType": "date"},
        },
    },
    CollectionNames.VERIFICATION_DEFINITIONS: {
        **_with_schema_version(_VERIFICATION_DEFINITION_REQUIRED),
        "properties": {
            **_with_schema_version(_VERIFICATION_DEFINITION_REQUIRED)["properties"],
            "repository_root": {"bsonType": "string"},
            "repo_config_hash": {"bsonType": "string"},
            "checks": {"bsonType": "array"},
            "trusted": {"bsonType": "bool"},
            "loaded_at": {"bsonType": "date"},
        },
    },
    CollectionNames.VERIFICATION_RUNS: {
        **_with_schema_version(_VERIFICATION_RUN_REQUIRED),
        "properties": {
            **_with_schema_version(_VERIFICATION_RUN_REQUIRED)["properties"],
            "task_id": {"bsonType": "string"},
            "verification_method": {"bsonType": "string"},
            "check_type": {"bsonType": "string"},
            "command": {"bsonType": "string"},
            "status": {"bsonType": "string"},
            "exit_code": {"bsonType": ["int", "long", "null"]},
            "duration_ms": {"bsonType": ["int", "long", "null"]},
            "started_at": {"bsonType": "date"},
            "finished_at": {"bsonType": ["date", "null"]},
            "commit": {"bsonType": ["string", "null"]},
            "working_tree_dirty": {"bsonType": ["bool", "null"]},
            "output_excerpt": {"bsonType": ["string", "null"]},
            "source": {"bsonType": "string"},
        },
    },
    CollectionNames.OUTCOME_SIGNALS: {
        **_with_schema_version(_OUTCOME_SIGNAL_REQUIRED),
        "properties": {
            **_with_schema_version(_OUTCOME_SIGNAL_REQUIRED)["properties"],
            "_id": {"bsonType": "string"},
            "task_id": {"bsonType": "string"},
            "signal_type": {"bsonType": "string"},
            "source": {"bsonType": "string"},
            "observed_at": {"bsonType": "date"},
            "payload": {"bsonType": "object"},
        },
    },
}


def apply_collection_validators(database) -> None:
    """Create collections or update validators idempotently."""
    existing = set(database.list_collection_names())
    for collection_name, json_schema in COLLECTION_VALIDATORS.items():
        validator = {"$jsonSchema": json_schema}
        if collection_name not in existing:
            database.create_collection(
                collection_name,
                validator=validator,
                validationLevel=_VALIDATION_OPTIONS["validationLevel"],
                validationAction=_VALIDATION_OPTIONS["validationAction"],
            )
            continue
        database.command(
            "collMod",
            collMod=collection_name,
            validator=validator,
            validationLevel=_VALIDATION_OPTIONS["validationLevel"],
            validationAction=_VALIDATION_OPTIONS["validationAction"],
        )
