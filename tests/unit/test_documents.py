from datetime import datetime, timezone

from cursor_model_router.database import documents as docs


def test_build_task_upsert_uses_set_on_insert_for_immutable_fields():
    identity = docs.ModelIdentity(
        model="claude-sonnet", model_id="claude-sonnet-4", model_params=[]
    )
    filter_, update = docs.build_task_upsert(
        task_id="task-guid-1",
        conversation_id="conv-1",
        repository_root="c:/work/repo",
        repository_commit=None,
        cursor_version="1.7.2",
        workspace_roots=["c:/work/repo"],
        identity=identity,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert filter_ == {"conversation_id": "conv-1"}
    assert update["$setOnInsert"]["_id"] == "task-guid-1"
    assert update["$setOnInsert"]["conversation_id"] == "conv-1"
    assert update["$setOnInsert"]["repository_root"] == "c:/work/repo"
    assert update["$set"]["model"] == "claude-sonnet"
    assert update["$addToSet"]["workspace_roots"] == {"$each": ["c:/work/repo"]}


def test_build_task_upsert_omits_add_to_set_when_no_workspace_roots():
    identity = docs.ModelIdentity(model=None, model_id=None, model_params=[])
    _, update = docs.build_task_upsert(
        task_id="task-guid-1",
        conversation_id="conv-1",
        repository_root=None,
        repository_commit=None,
        cursor_version=None,
        workspace_roots=[],
        identity=identity,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert "$addToSet" not in update


def test_build_task_event_carries_idempotency_id():
    event = docs.build_task_event(
        event_key="abc123",
        task_id="task-guid-1",
        generation_id="gen-1",
        event_type="pre_tool_use",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        tool_name="Shell",
        duration_ms=12.75,
    )

    assert event["_id"] == "abc123"
    assert event["task_id"] == "task-guid-1"
    assert "conversation_id" not in event
    assert event["tool_name"] == "Shell"
    assert event["duration_ms"] == 12
    assert event["schema_version"] == docs.SCHEMA_VERSION


def test_build_classification_document_defaults_provider_fields_to_none():
    document = docs.build_classification_document(
        task_id="conversation-task-guid-1",
        generation_task_id="generation-task-guid-1",
        source="rules",
        category="debugging",
        subcategory=None,
        primary_language=None,
        intent=None,
        cross_file_scope=None,
        complexity=None,
        confidence=0.5,
        evidence={},
    )

    assert document["provider"] is None
    assert document["task_id"] == "conversation-task-guid-1"
    assert document["generation_task_id"] == "generation-task-guid-1"
    assert "conversation_id" not in document
    assert "classifier_version" not in document
    assert "taxonomy_version" not in document
    assert document["created_at"] is not None


def test_build_generation_upsert_captures_prompt_time_model_via_set_on_insert():
    identity = docs.ModelIdentity(model="claude-sonnet", model_id="claude-sonnet-4")
    filter_, update = docs.build_generation_upsert(
        generation_task_id="gen-task-1",
        task_id="task-guid-1",
        generation_id="gen-1",
        repository_root="c:/work/repo",
        identity=identity,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert filter_ == {"task_id": "task-guid-1", "generation_id": "gen-1"}
    assert update["$setOnInsert"]["_id"] == "gen-task-1"
    assert update["$setOnInsert"]["model"] == "claude-sonnet"
    assert update["$setOnInsert"]["model_id"] == "claude-sonnet-4"
    assert update["$setOnInsert"]["repository_root"] == "c:/work/repo"
    assert update["$setOnInsert"]["status"] == "in_progress"
    # Model/repository are only ever set on insert, never overwritten by
    # later activity in the same generation.
    assert "model" not in update["$set"]
    assert "repository_root" not in update["$set"]


def test_build_generation_prompt_update_only_applies_when_prompt_missing():
    filter_, update = docs.build_generation_prompt_update(
        task_id="task-guid-1",
        generation_id="gen-1",
        prompt_preview="fix the bug",
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert filter_ == {
        "task_id": "task-guid-1",
        "generation_id": "gen-1",
        "prompt_preview": {"$exists": False},
    }
    assert update["$set"]["prompt_preview"] == "fix the bug"


def test_build_generation_status_update_sets_finished_at_for_terminal_status():
    filter_, update = docs.build_generation_status_update(
        task_id="task-guid-1",
        generation_id="gen-1",
        status="completed",
        loop_count=2,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert filter_ == {"task_id": "task-guid-1", "generation_id": "gen-1"}
    assert update["$set"]["status"] == "completed"
    assert update["$set"]["loop_count"] == 2
    assert update["$set"]["finished_at"] is not None


def test_build_generation_status_update_omits_finished_at_while_in_progress():
    _, update = docs.build_generation_status_update(
        task_id="task-guid-1",
        generation_id="gen-1",
        status="in_progress",
        loop_count=None,
        occurred_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
    )

    assert "finished_at" not in update["$set"]
    assert "loop_count" not in update["$set"]
