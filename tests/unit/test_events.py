import mongomock
import pytest

from cursor_model_router.collector.events import ParsedEnvelope, apply_envelope, parse_hook_payload
from cursor_model_router.common.config import RouterConfig
from cursor_model_router.common.constants import UNSCOPED_GENERATION_ID
from cursor_model_router.database.repositories import TaskRepositorySync


@pytest.fixture
def config() -> RouterConfig:
    return RouterConfig()


@pytest.fixture
def database():
    client = mongomock.MongoClient()
    return client["test_db"]


def test_parse_hook_payload_ignores_unknown_events(config):
    assert parse_hook_payload({"hook_event_name": "workspaceOpen"}, config) is None


def test_parse_hook_payload_ignores_events_without_conversation_id(config):
    assert parse_hook_payload({"hook_event_name": "sessionStart"}, config) is None


def test_parse_hook_payload_redacts_and_truncates_prompt(config):
    raw = {
        "hook_event_name": "beforeSubmitPrompt",
        "conversation_id": "conv-1",
        "prompt": "here is my api_key: supersecretvalue123456",
        "workspace_roots": ["C:\\work\\repo"],
    }
    envelope = parse_hook_payload(raw, config)
    assert envelope is not None
    assert "supersecretvalue123456" not in envelope.fields["prompt_preview"]
    assert envelope.repository_root == "c:/work/repo"


def test_parse_hook_payload_pre_tool_use_extracts_command(config):
    raw = {
        "hook_event_name": "preToolUse",
        "conversation_id": "conv-1",
        "tool_name": "Shell",
        "tool_input": {"command": "npm install"},
        "workspace_roots": ["C:\\work\\repo"],
    }
    envelope = parse_hook_payload(raw, config)
    assert envelope.fields["tool_name"] == "Shell"
    assert envelope.fields["command"] == "npm install"


def test_envelope_round_trips_through_json(config):
    raw = {
        "hook_event_name": "stop",
        "conversation_id": "conv-1",
        "generation_id": "gen-1",
        "model": "claude-sonnet",
        "status": "completed",
        "loop_count": 0,
        "workspace_roots": ["C:\\work\\repo"],
    }
    envelope = parse_hook_payload(raw, config)
    roundtripped = ParsedEnvelope.from_json(envelope.to_json())
    assert roundtripped.conversation_id == envelope.conversation_id
    assert roundtripped.fields == envelope.fields


def test_apply_envelope_upserts_task_and_event(config, database):
    raw = {
        "hook_event_name": "preToolUse",
        "conversation_id": "conv-1",
        "generation_id": "gen-1",
        "model": "claude-sonnet",
        "tool_name": "Shell",
        "tool_input": {"command": "echo hi"},
        "workspace_roots": ["C:\\work\\repo"],
    }
    envelope = parse_hook_payload(raw, config)
    repo = TaskRepositorySync(database)

    apply_envelope(repo, envelope)

    task = database["tasks"].find_one({"conversation_id": "conv-1"})
    assert task is not None
    assert task["_id"] != task["conversation_id"]
    assert task["model"] == "claude-sonnet"
    assert task["repository_root"] == "c:/work/repo"

    events = list(database["task_events"].find({"task_id": task["_id"]}))
    assert len(events) == 1
    assert "conversation_id" not in events[0]
    assert events[0]["tool_name"] == "Shell"
    assert events[0]["generation_id"] == "gen-1"

    generation = database["task_generations"].find_one(
        {"task_id": task["_id"], "generation_id": "gen-1"}
    )
    assert generation is not None
    assert generation["model"] == "claude-sonnet"
    assert generation["repository_root"] == "c:/work/repo"


def test_apply_envelope_uses_explicit_fallback_identity_when_generation_id_missing(
    config, database
):
    raw = {
        "hook_event_name": "preToolUse",
        "conversation_id": "conv-1",
        "tool_name": "Shell",
        "tool_input": {"command": "echo hi"},
        "workspace_roots": ["C:\\work\\repo"],
    }
    envelope = parse_hook_payload(raw, config)
    assert envelope.generation_id == UNSCOPED_GENERATION_ID
    repo = TaskRepositorySync(database)

    apply_envelope(repo, envelope)

    task = database["tasks"].find_one({"conversation_id": "conv-1"})
    generation = database["task_generations"].find_one(
        {"task_id": task["_id"], "generation_id": UNSCOPED_GENERATION_ID}
    )
    assert generation is not None


def test_apply_envelope_captures_generation_model_only_at_first_event(config, database):
    repo = TaskRepositorySync(database)

    first_raw = {
        "hook_event_name": "beforeSubmitPrompt",
        "conversation_id": "conv-1",
        "generation_id": "gen-1",
        "model": "claude-sonnet",
        "prompt": "fix the bug",
        "workspace_roots": ["C:\\work\\repo"],
    }
    apply_envelope(repo, parse_hook_payload(first_raw, config))

    second_raw = {
        "hook_event_name": "postToolUse",
        "conversation_id": "conv-1",
        "generation_id": "gen-1",
        "model": "gpt-5",
        "tool_name": "Shell",
        "tool_input": {"command": "echo hi"},
        "workspace_roots": ["C:\\work\\repo"],
    }
    apply_envelope(repo, parse_hook_payload(second_raw, config))

    task = database["tasks"].find_one({"conversation_id": "conv-1"})
    generation = database["task_generations"].find_one(
        {"task_id": task["_id"], "generation_id": "gen-1"}
    )
    # Later events in the same generation never overwrite the model that was
    # active when the generation was first observed.
    assert generation["model"] == "claude-sonnet"
    assert generation["prompt_preview"] == "fix the bug"


def test_apply_envelope_second_generation_does_not_affect_first(config, database):
    repo = TaskRepositorySync(database)

    for generation_id, prompt in (("gen-1", "fix the bug"), ("gen-2", "add a new feature")):
        raw = {
            "hook_event_name": "beforeSubmitPrompt",
            "conversation_id": "conv-1",
            "generation_id": generation_id,
            "prompt": prompt,
            "workspace_roots": ["C:\\work\\repo"],
        }
        apply_envelope(repo, parse_hook_payload(raw, config))

    task = database["tasks"].find_one({"conversation_id": "conv-1"})
    generations = {
        doc["generation_id"]: doc
        for doc in database["task_generations"].find({"task_id": task["_id"]})
    }
    assert len(generations) == 2
    assert generations["gen-1"]["prompt_preview"] == "fix the bug"
    assert generations["gen-2"]["prompt_preview"] == "add a new feature"


def test_apply_envelope_is_idempotent_for_duplicate_events(config, database):
    raw = {
        "hook_event_name": "afterFileEdit",
        "conversation_id": "conv-1",
        "generation_id": "gen-1",
        "file_path": "C:\\work\\repo\\src\\main.py",
        "edits": [{"old_string": "a", "new_string": "b"}],
        "workspace_roots": ["C:\\work\\repo"],
    }
    envelope = parse_hook_payload(raw, config)
    repo = TaskRepositorySync(database)

    # Simulate the hook firing twice for the exact same event (retry/duplicate delivery).
    frozen_envelope = ParsedEnvelope.from_json(envelope.to_json())
    apply_envelope(repo, frozen_envelope)
    apply_envelope(repo, frozen_envelope)

    task = database["tasks"].find_one({"conversation_id": "conv-1"})
    events = list(database["task_events"].find({"task_id": task["_id"]}))
    assert len(events) == 1


def test_apply_envelope_sets_generation_status_on_stop_not_conversation_status(config, database):
    raw = {
        "hook_event_name": "stop",
        "conversation_id": "conv-1",
        "generation_id": "gen-1",
        "status": "completed",
        "loop_count": 2,
        "workspace_roots": ["C:\\work\\repo"],
    }
    envelope = parse_hook_payload(raw, config)
    repo = TaskRepositorySync(database)

    apply_envelope(repo, envelope)

    task = database["tasks"].find_one({"conversation_id": "conv-1"})
    generation = database["task_generations"].find_one(
        {"task_id": task["_id"], "generation_id": "gen-1"}
    )
    assert generation["status"] == "completed"
    assert generation["loop_count"] == 2
    assert generation["finished_at"] is not None
    # `stop` ends one turn, not the whole conversation.
    assert task.get("status") is None


def test_apply_envelope_sets_conversation_status_on_session_end(config, database):
    repo = TaskRepositorySync(database)
    apply_envelope(
        repo,
        parse_hook_payload(
            {
                "hook_event_name": "beforeSubmitPrompt",
                "conversation_id": "conv-1",
                "generation_id": "gen-1",
                "prompt": "fix the bug",
                "workspace_roots": ["C:\\work\\repo"],
            },
            config,
        ),
    )

    raw = {
        "hook_event_name": "sessionEnd",
        "conversation_id": "conv-1",
        "reason": "completed",
        "workspace_roots": ["C:\\work\\repo"],
    }
    apply_envelope(repo, parse_hook_payload(raw, config))

    task = database["tasks"].find_one({"conversation_id": "conv-1"})
    assert task["status"] == "completed"
    assert task["finished_at"] is not None
