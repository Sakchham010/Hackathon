"""Integration coverage for the hook -> MongoDB (or spool) write path."""

from __future__ import annotations

import concurrent.futures

from cursor_model_router.collector.service import drain, handle_raw_event
from cursor_model_router.common.config import RouterConfig

from .conftest import requires_mongo


def _tool_use_payload(conversation_id: str, tool_use_id: str) -> dict:
    return {
        "hook_event_name": "postToolUse",
        "conversation_id": conversation_id,
        "generation_id": "gen-1",
        "tool_name": "Shell",
        "tool_use_id": tool_use_id,
        "tool_input": {"command": f"echo {tool_use_id}"},
        "duration": 10,
        "workspace_roots": ["c:/work/repo"],
        "model": "claude-sonnet",
    }


@requires_mongo
def test_concurrent_hook_events_all_persist_without_duplicates(
    router_config: RouterConfig, sync_client
):
    conversation_id = "conv-concurrent"
    payloads = [_tool_use_payload(conversation_id, f"tool-{i}") for i in range(20)]

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda p: handle_raw_event(p, router_config), payloads))

    database = sync_client[router_config.database_name]
    task = database["tasks"].find_one({"conversation_id": conversation_id})
    assert task is not None
    events = list(database["task_events"].find({"task_id": task["_id"]}))
    assert len(events) == 20
    assert task["_id"] != conversation_id


@requires_mongo
def test_duplicate_event_delivery_is_idempotent(router_config: RouterConfig, sync_client):
    conversation_id = "conv-duplicate"
    payload = _tool_use_payload(conversation_id, "tool-fixed")

    handle_raw_event(payload, router_config)
    handle_raw_event(payload, router_config)

    database = sync_client[router_config.database_name]
    task = database["tasks"].find_one({"conversation_id": conversation_id})
    events = list(database["task_events"].find({"task_id": task["_id"]}))
    assert len(events) == 1


@requires_mongo
def test_spool_recovery_after_mongo_downtime(router_config: RouterConfig, sync_client, tmp_path):
    unreachable_config = RouterConfig(
        mongo_uri="mongodb://127.0.0.1:1",
        database_name=router_config.database_name,
    )
    unreachable_config.home_dir = str(tmp_path / "home")

    conversation_id = "conv-spooled"
    payload = _tool_use_payload(conversation_id, "tool-spooled")

    handle_raw_event(payload, unreachable_config)

    spooled_files = list(unreachable_config.spool_dir.glob("*.jsonl"))
    assert len(spooled_files) == 1

    # Point the spool at the real database and drain it.
    unreachable_config.mongo_uri = router_config.mongo_uri
    drained_count = drain(unreachable_config)

    assert drained_count == 1
    assert list(unreachable_config.spool_dir.glob("*.jsonl")) == []

    database = sync_client[router_config.database_name]
    task = database["tasks"].find_one({"conversation_id": conversation_id})
    events = list(database["task_events"].find({"task_id": task["_id"]}))
    assert len(events) == 1
