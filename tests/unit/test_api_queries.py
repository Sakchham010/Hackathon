from datetime import datetime, timezone
from pathlib import Path

import mongomock

from cursor_model_router.api.queries import ReviewQueries


def _database():
    return mongomock.MongoClient()["review_api_test"]


def _seed_task(database, *, task_id="task-1", status="completed", repository_root=None):
    now = datetime.now(timezone.utc)
    database["tasks"].insert_one(
        {
            "_id": task_id,
            "conversation_id": f"conversation-{task_id}",
            "status": status,
            "repository_root": repository_root,
            "started_at": now,
            "updated_at": now,
            "finished_at": now,
        }
    )
    database["task_generations"].insert_one(
        {
            "_id": f"generation-task-{task_id}",
            "task_id": task_id,
            "generation_id": "generation-1",
            "prompt_preview": "Fix the unique index",
            "model": "composer-2",
            "status": status,
            "started_at": now,
        }
    )


def test_needs_review_excludes_tasks_with_human_evidence():
    database = _database()
    _seed_task(database)
    _seed_task(database, task_id="task-2")
    database["verification_runs"].insert_one(
        {
            "task_id": "task-2",
            "source": "user_submitted",
            "status": "passed",
            "check_type": "behavior",
        }
    )

    rows = ReviewQueries(database).list_conversations(filter_name="needs_review")

    assert [row["task_id"] for row in rows] == ["task-1"]


def test_detail_joins_classification_signals_and_bounded_activity():
    database = _database()
    _seed_task(database)
    database["task_classifications"].insert_one(
        {
            "task_id": "task-1",
            "generation_task_id": "generation-task-task-1",
            "source": "rules",
            "category": "debugging",
            "confidence": 0.9,
        }
    )
    database["task_events"].insert_many(
        [
            {
                "_id": "event-1",
                "task_id": "task-1",
                "generation_id": "generation-1",
                "event_type": "after_file_edit",
                "file_path": "C:/work/repo/src/schema.py",
                "occurred_at": datetime.now(timezone.utc),
            },
            {
                "_id": "event-2",
                "task_id": "task-1",
                "generation_id": "generation-1",
                "event_type": "post_tool_use",
                "command": "pytest tests/unit/test_schema.py",
                "occurred_at": datetime.now(timezone.utc),
            },
        ]
    )
    database["outcome_signals"].insert_one(
        {
            "_id": "signal-1",
            "task_id": "generation-task-task-1",
            "signal_type": "build_test_activity",
            "payload": {"observed": True},
            "observed_at": datetime.now(timezone.utc),
        }
    )

    detail = ReviewQueries(database).get_conversation("conversation-task-1")

    assert detail is not None
    generation = detail["generations"][0]
    assert generation["classifications"][0]["category"] == "debugging"
    assert generation["activity"]["tool_failures"] == 0
    assert generation["activity"]["commands"] == ["pytest tests/unit/test_schema.py"]
    assert generation["activity"]["edited_files"] == ["C:/work/repo/src/schema.py"]
    assert generation["outcome_signals"][0]["signal_type"] == "build_test_activity"


def test_activity_summary_excludes_tool_reads_from_edited_files():
    database = _database()
    _seed_task(database)
    database["task_events"].insert_many(
        [
            {
                "_id": "read-event",
                "task_id": "task-1",
                "generation_id": "generation-1",
                "event_type": "pre_tool_use",
                "file_path": "C:/work/repo/src/other.py",
                "occurred_at": datetime.now(timezone.utc),
            },
            {
                "_id": "edit-event",
                "task_id": "task-1",
                "generation_id": "generation-1",
                "event_type": "after_file_edit",
                "file_path": "C:/work/repo/src/schema.py",
                "occurred_at": datetime.now(timezone.utc),
            },
        ]
    )

    detail = ReviewQueries(database).get_conversation("conversation-task-1")

    assert detail is not None
    assert detail["generations"][0]["activity"]["edited_files"] == [
        "C:/work/repo/src/schema.py"
    ]


def test_activity_summary_excludes_repository_root_from_edited_files():
    database = _database()
    _seed_task(database, repository_root="C:/work/repo")
    database["task_events"].insert_many(
        [
            {
                "_id": "root-event",
                "task_id": "task-1",
                "generation_id": "generation-1",
                "event_type": "after_file_edit",
                "file_path": "C:/work/repo",
                "occurred_at": datetime.now(timezone.utc),
            },
            {
                "_id": "edit-event",
                "task_id": "task-1",
                "generation_id": "generation-1",
                "event_type": "after_file_edit",
                "file_path": "C:/work/repo/src/schema.py",
                "occurred_at": datetime.now(timezone.utc),
            },
        ]
    )

    detail = ReviewQueries(database).get_conversation("conversation-task-1")

    assert detail is not None
    activity = detail["generations"][0]["activity"]
    assert activity["edited_files"] == ["C:/work/repo/src/schema.py"]
    assert activity["repository_relative_files"] == [str(Path("src/schema.py"))]
