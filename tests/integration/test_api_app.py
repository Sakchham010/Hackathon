from datetime import datetime, timezone

from fastapi.testclient import TestClient

from cursor_model_router.api.app import create_app
from tests.integration.conftest import requires_mongo


@requires_mongo
def test_review_api_records_verification_in_real_mongo(
    router_config, sync_client, database_name
):
    database = sync_client[database_name]
    now = datetime.now(timezone.utc)
    database["tasks"].insert_one(
        {
            "_id": "integration-api-task",
            "conversation_id": "integration-api-conversation",
            "status": "completed",
            "started_at": now,
            "updated_at": now,
            "finished_at": now,
            "schema_version": 5,
        }
    )
    database["task_generations"].insert_one(
        {
            "_id": "integration-api-generation-task",
            "task_id": "integration-api-task",
            "generation_id": "integration-api-generation",
            "prompt_preview": "Verify the review API",
            "status": "completed",
            "started_at": now,
            "schema_version": 5,
        }
    )

    with TestClient(create_app(router_config, database=database)) as client:
        response = client.post(
            "/api/conversations/integration-api-task/verification",
            json={
                "status": "passed",
                "verification_method": "automated",
                "check_type": "test",
                "command": "pytest tests/integration/test_api_app.py",
            },
        )

    assert response.status_code == 201
    assert response.json()["recorded"] is True
    assert database["verification_runs"].count_documents(
        {"task_id": "integration-api-task", "source": "user_submitted"}
    ) == 1
