from datetime import datetime, timezone

import mongomock

from cursor_model_router.database.documents import SCHEMA_VERSION
from cursor_model_router.export import build_export_rows


def test_export_joins_generations_and_conversation_level_documents_by_task_id():
    database = mongomock.MongoClient()["test_db"]
    task_id = "task-guid-1"
    generation_task_id = "generation-task-guid-1"
    database["tasks"].insert_one(
        {
            "_id": task_id,
            "conversation_id": "conv-1",
            "started_at": datetime.now(timezone.utc),
            "schema_version": SCHEMA_VERSION,
        }
    )
    database["task_generations"].insert_one(
        {
            "_id": generation_task_id,
            "task_id": task_id,
            "generation_id": "gen-1",
            "prompt_preview": "fix the bug",
        }
    )
    database["task_classifications"].insert_one(
        {"task_id": task_id, "generation_task_id": generation_task_id, "category": "debugging"}
    )
    # Conversation-level signal (keyed by the conversation task id).
    database["outcome_signals"].insert_one({"task_id": task_id, "signal_type": "agent_status"})
    # Generation-level signal (keyed by the generation's own task id).
    database["outcome_signals"].insert_one(
        {"task_id": generation_task_id, "signal_type": "tool_failure"}
    )
    database["verification_runs"].insert_one({"task_id": task_id, "status": "passed"})

    row = next(build_export_rows(database))

    assert row["task_id"] == task_id
    assert row["conversation_id"] == "conv-1"
    assert len(row["generations"]) == 1
    assert len(row["outcome_signals"]) == 1
    assert row["outcome_signals"][0]["signal_type"] == "agent_status"
    assert len(row["verification_runs"]) == 1

    generation_row = row["generations"][0]
    assert generation_row["generation_id"] == "gen-1"
    assert len(generation_row["classifications"]) == 1
    assert generation_row["classifications"][0]["category"] == "debugging"
    assert len(generation_row["outcome_signals"]) == 1
    assert generation_row["outcome_signals"][0]["signal_type"] == "tool_failure"
