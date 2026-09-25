"""Integration coverage for the classification, outcome, and verification workers."""

from __future__ import annotations

import sys
from datetime import datetime, timezone

import pytest

from cursor_model_router.classification.worker import classify_batch
from cursor_model_router.common.config import RouterConfig, TrustedRepositoryConfig
from cursor_model_router.common.ids import new_id
from cursor_model_router.database.documents import SCHEMA_VERSION
from cursor_model_router.outcomes.ingestion import record_user_submitted_result
from cursor_model_router.outcomes.worker import extract_signals_batch
from cursor_model_router.verification.worker import run_pending_checks

from .conftest import requires_mongo


async def _seed_finished_conversation(
    database,
    conversation_id: str,
    *,
    repository_root: str | None = None,
    status: str = "completed",
) -> str:
    """Seed a conversation-level task and return its task id."""
    now = datetime.now(timezone.utc)
    task_id = new_id()
    document = {
        "_id": task_id,
        "conversation_id": conversation_id,
        "status": status,
        "repository_root": repository_root,
        "started_at": now,
        "updated_at": now,
        "model": "claude-sonnet",
        "schema_version": SCHEMA_VERSION,
    }
    if status != "in_progress":
        document["finished_at"] = now
    await database["tasks"].insert_one(document)
    return task_id


async def _seed_generation(
    database,
    task_id: str,
    generation_id: str,
    *,
    prompt: str,
    status: str = "completed",
) -> str:
    """Seed a generation task beneath ``task_id`` and return its own task id."""
    now = datetime.now(timezone.utc)
    generation_task_id = new_id()
    await database["task_generations"].insert_one(
        {
            "_id": generation_task_id,
            "task_id": task_id,
            "generation_id": generation_id,
            "prompt_preview": prompt,
            "status": status,
            "started_at": now,
            "updated_at": now,
            "finished_at": now if status != "in_progress" else None,
            "model": "claude-sonnet",
            "schema_version": SCHEMA_VERSION,
        }
    )
    return generation_task_id


async def _seed_failure_event(database, task_id: str, generation_id: str, event_key: str) -> None:
    await database["task_events"].insert_one(
        {
            "_id": event_key,
            "task_id": task_id,
            "generation_id": generation_id,
            "event_type": "post_tool_use_failure",
            "occurred_at": datetime.now(timezone.utc),
            "metadata": {"error_message": "Unhandled exception: stack trace at line 4"},
            "schema_version": SCHEMA_VERSION,
        }
    )


@requires_mongo
@pytest.mark.asyncio
async def test_classify_batch_is_idempotent_across_reruns(
    async_database, router_config: RouterConfig
):
    task_id = await _seed_finished_conversation(async_database, "conv-classify-1")
    generation_task_id = await _seed_generation(
        async_database, task_id, "gen-1", prompt="Find and fix this deadlock"
    )

    first_pass = await classify_batch(async_database, router_config)
    second_pass_no_more_pending = await classify_batch(async_database, router_config)

    docs = [
        doc
        async for doc in async_database["task_classifications"].find(
            {"generation_task_id": generation_task_id}
        )
    ]
    assert first_pass == 1
    assert second_pass_no_more_pending == 0
    assert len(docs) == 1
    assert docs[0]["category"] == "debugging"


@requires_mongo
@pytest.mark.asyncio
async def test_classify_batch_keeps_generations_independent(
    async_database, router_config: RouterConfig
):
    """Two generations in one conversation must classify independently, and a
    later generation's activity must never rewrite an earlier, already
    classified generation's intent."""
    # The conversation itself is still open (no sessionEnd yet), matching a
    # real multi-turn session where earlier turns finish before later ones.
    task_id = await _seed_finished_conversation(
        async_database, "conv-classify-2", status="in_progress"
    )
    gen1_task_id = await _seed_generation(
        async_database, task_id, "gen-1", prompt="Find and fix this deadlock"
    )
    gen2_task_id = await _seed_generation(
        async_database,
        task_id,
        "gen-2",
        prompt="Add a new settings page",
        status="in_progress",
    )

    first_pass = await classify_batch(async_database, router_config)
    gen1_docs = [
        doc
        async for doc in async_database["task_classifications"].find(
            {"generation_task_id": gen1_task_id}
        )
    ]
    gen2_docs = [
        doc
        async for doc in async_database["task_classifications"].find(
            {"generation_task_id": gen2_task_id}
        )
    ]
    assert first_pass == 1
    assert len(gen1_docs) == 1
    assert gen1_docs[0]["category"] == "debugging"
    assert gen2_docs == []  # gen-2 has not finished yet, and neither has the conversation

    # gen-2 later finishes (its own `stop`) with an unrelated tool failure;
    # classifying it must never revisit gen-1, and the failure must not flip
    # gen-2's own category.
    await async_database["task_generations"].update_one(
        {"_id": gen2_task_id}, {"$set": {"status": "completed"}}
    )
    await _seed_failure_event(async_database, task_id, "gen-2", "conv-classify-2-failure")

    second_pass = await classify_batch(async_database, router_config)
    gen1_docs_after = [
        doc
        async for doc in async_database["task_classifications"].find(
            {"generation_task_id": gen1_task_id}
        )
    ]
    gen2_docs_after = [
        doc
        async for doc in async_database["task_classifications"].find(
            {"generation_task_id": gen2_task_id}
        )
    ]

    assert second_pass == 1
    assert gen1_docs_after == gen1_docs
    assert len(gen2_docs_after) == 1
    assert gen2_docs_after[0]["category"] == "feature"
    assert gen2_docs_after[0]["evidence"]["had_tool_failure"] is True


@requires_mongo
@pytest.mark.asyncio
async def test_extract_signals_batch_records_expected_signal_types(async_database):
    task_id = await _seed_finished_conversation(async_database, "conv-signals-1")
    generation_task_id = await _seed_generation(
        async_database, task_id, "gen-1", prompt="It crashes on startup"
    )
    await _seed_failure_event(async_database, task_id, "gen-1", "conv-signals-1-event-1")

    processed = await extract_signals_batch(async_database)

    conversation_signal_types = {
        doc["signal_type"]
        async for doc in async_database["outcome_signals"].find({"task_id": task_id})
    }
    generation_signal_types = {
        doc["signal_type"]
        async for doc in async_database["outcome_signals"].find({"task_id": generation_task_id})
    }

    assert processed == 1
    assert "agent_status" in conversation_signal_types
    assert "tool_failure" in generation_signal_types

    # Re-running should not duplicate or reprocess the already-signaled task.
    second_pass = await extract_signals_batch(async_database)
    assert second_pass == 0


@requires_mongo
@pytest.mark.asyncio
async def test_user_submitted_results_are_recorded(async_database):
    task_id = await _seed_finished_conversation(async_database, "conv-user-1")
    first = await record_user_submitted_result(
        async_database,
        task_id=task_id,
        status="passed",
    )
    second = await record_user_submitted_result(
        async_database,
        task_id=task_id,
        status="passed",
    )

    assert first is True
    assert second is True

    runs = [doc async for doc in async_database["verification_runs"].find({"task_id": task_id})]
    assert len(runs) == 2
    assert {run["verification_method"] for run in runs} == {"manual"}
    assert {run["check_type"] for run in runs} == {"other"}


@requires_mongo
@pytest.mark.asyncio
async def test_run_pending_checks_executes_trusted_repo_commands_and_respects_timeout(
    async_database, router_config: RouterConfig, tmp_path
):
    repo_root = tmp_path / "trusted-repo"
    repo_root.mkdir()
    # Single-quoted YAML scalars treat backslashes literally, which matters
    # here because sys.executable is a Windows path.
    quick_command = f'{sys.executable} -c "pass"'
    slow_command = f'{sys.executable} -c "import time; time.sleep(5)"'
    (repo_root / ".cursor-model-router.yaml").write_text(
        "version: 1\n"
        "checks:\n"
        "  - name: quick_pass\n"
        "    check_type: test\n"
        f"    command: '{quick_command}'\n"
        "  - name: slow_timeout\n"
        "    check_type: build\n"
        f"    command: '{slow_command}'\n"
        "    timeout_seconds: 1\n",
        encoding="utf-8",
    )

    repo_root_str = repo_root.as_posix()
    router_config.verification.trusted_repositories = [
        TrustedRepositoryConfig(path_glob=f"{repo_root_str}*", max_command_timeout_seconds=30)
    ]

    task_id = await _seed_finished_conversation(
        async_database, "conv-verify-1", repository_root=repo_root_str
    )

    processed = await run_pending_checks(async_database, router_config)
    assert processed == 1

    runs = [
        doc async for doc in async_database["verification_runs"].find({"task_id": task_id})
    ]
    assert {run["command"] for run in runs} == {quick_command, slow_command}
    assert {run["status"] for run in runs} == {"passed", "timed_out"}
    assert {run["verification_method"] for run in runs} == {"automated"}
    assert {run["check_type"] for run in runs} == {"test", "build"}

    # A repository with no trust entry gets a single 'skipped' marker, never reprocessed.
    await _seed_finished_conversation(
        async_database,
        "conv-verify-untrusted",
        repository_root="c:/untrusted/repo",
    )
    processed_untrusted = await run_pending_checks(async_database, router_config)
    assert processed_untrusted == 1
    second_pass = await run_pending_checks(async_database, router_config)
    assert second_pass == 0
