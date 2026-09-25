from datetime import datetime, timezone

import mongomock
from fastapi.testclient import TestClient

from cursor_model_router.api.app import create_app
from cursor_model_router.common.config import RouterConfig


def test_review_api_lists_detail_and_records_human_evidence():
    database = mongomock.MongoClient()["review_app_test"]
    now = datetime.now(timezone.utc)
    database["tasks"].insert_one(
        {
            "_id": "task-1",
            "conversation_id": "conversation-1",
            "status": "completed",
            "repository_root": "C:/work/example",
            "started_at": now,
            "updated_at": now,
            "finished_at": now,
        }
    )
    database["task_generations"].insert_one(
        {
            "_id": "generation-task-1",
            "task_id": "task-1",
            "generation_id": "generation-1",
            "prompt_preview": "Fix the bug",
            "status": "completed",
            "started_at": now,
        }
    )

    client = TestClient(
        create_app(
            RouterConfig(database_name="review_app_test"),
            database=database,
        )
    )

    inbox = client.get("/api/conversations")
    assert inbox.status_code == 200
    assert inbox.json()[0]["conversation_id"] == "conversation-1"

    detail = client.get("/api/conversations/conversation-1")
    assert detail.status_code == 200
    assert detail.json()["generations"][0]["prompt_preview"] == "Fix the bug"

    recorded = client.post(
        "/api/conversations/task-1/verification",
        json={
            "status": "passed",
            "verification_method": "manual",
            "check_type": "behavior",
            "output": "Checked the changed behavior in the app.",
        },
    )
    assert recorded.status_code == 201
    assert recorded.json()["recorded"] is True
    assert recorded.json()["run"]["source"] == "user_submitted"

    assert client.get("/api/conversations").json() == []
