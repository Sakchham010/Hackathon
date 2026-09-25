"""Asynchronous worker that runs trusted, repository-defined verification checks.

Polls for finished tasks the same way the classification/outcome workers do.
For each task: resolve its repository, check central trust, load the
repository's own ``.cursor-model-router.yaml``, and run every defined check.
Repositories with no trust entry or no config file get a single ``skipped``
marker recorded so they are not rescanned on every poll.
"""

from __future__ import annotations

from pathlib import Path

from pymongo.asynchronous.database import AsyncDatabase

from cursor_model_router.common.config import RouterConfig
from cursor_model_router.common.constants import (
    OutcomeSource,
    VerificationCheckType,
    VerificationMethod,
    VerificationRunStatus,
)
from cursor_model_router.common.time_utils import utc_now
from cursor_model_router.database.documents import (
    build_verification_definition,
    build_verification_run,
)
from cursor_model_router.database.repositories import TaskReaderAsync, VerificationRepositoryAsync
from cursor_model_router.verification.git_info import get_commit, is_working_tree_dirty
from cursor_model_router.verification.repo_config import load_repo_config
from cursor_model_router.verification.runner import run_check
from cursor_model_router.verification.trust import find_trust_entry


def _record_skip(task_id: str, repository_root: str | None) -> dict:
    now = utc_now()
    return build_verification_run(
        task_id=task_id,
        verification_method=VerificationMethod.NOT_VERIFIABLE,
        check_type=VerificationCheckType.OTHER,
        command="",
        status=VerificationRunStatus.SKIPPED,
        exit_code=None,
        duration_ms=0,
        started_at=now,
        finished_at=now,
        commit=None,
        working_tree_dirty=None,
        output_excerpt=(
            f"No trusted verification config found for {repository_root or 'unknown repository'}."
        ),
        source=OutcomeSource.ROUTER_VERIFICATION,
    )


async def run_pending_checks(
    database: AsyncDatabase, config: RouterConfig, *, limit: int = 100
) -> int:
    reader = TaskReaderAsync(database)

    processed = 0
    async for task in reader.find_finished_tasks_needing_router_verification(limit=limit):
        processed += await run_checks_for_task(database, config, task)
    return processed


async def run_checks_for_task(
    database: AsyncDatabase, config: RouterConfig, task: dict
) -> int:
    """Run trusted checks for one task, independent of the pending-task scan."""
    verification = VerificationRepositoryAsync(database)
    task_id = task["_id"]
    repository_root = task.get("repository_root")

    if not repository_root:
        await verification.record_run(_record_skip(task_id, repository_root))
        return 1

    trust_entry = find_trust_entry(repository_root, config.verification.trusted_repositories)
    if trust_entry is None:
        await verification.record_run(_record_skip(task_id, repository_root))
        return 1

    repo_root_path = Path(repository_root)
    loaded = load_repo_config(repo_root_path, config.verification.repo_config_file_name)
    if loaded is None:
        await verification.record_run(_record_skip(task_id, repository_root))
        return 1

    repo_config, config_hash = loaded
    definition_document = build_verification_definition(
        repository_root=repository_root,
        repo_config_hash=config_hash,
        checks=[check.model_dump() for check in repo_config.checks],
        trusted=True,
    )
    await verification.upsert_definition(definition_document)

    commit = get_commit(repo_root_path)
    working_tree_dirty = is_working_tree_dirty(repo_root_path)

    for check in repo_config.checks:
        effective_timeout = min(
            check.timeout_seconds or config.verification.default_command_timeout_seconds,
            trust_entry.max_command_timeout_seconds,
        )

        started_marker = build_verification_run(
            task_id=task_id,
            verification_method=VerificationMethod.AUTOMATED,
            check_type=check.check_type,
            command=check.command,
            status=VerificationRunStatus.RUNNING,
            exit_code=None,
            duration_ms=None,
            started_at=utc_now(),
            finished_at=None,
            commit=commit,
            working_tree_dirty=working_tree_dirty,
            output_excerpt=None,
            source=OutcomeSource.ROUTER_VERIFICATION,
        )
        run_id = await verification.record_run(started_marker)
        if run_id is None:
            continue

        result = run_check(
            check,
            repo_root=repo_root_path,
            effective_timeout_seconds=effective_timeout,
            max_output_chars=config.redaction.max_command_output_chars,
        )
        await verification.update_run_result(
            run_id=run_id,
            status=result.status,
            exit_code=result.exit_code,
            duration_ms=result.duration_ms,
            finished_at=result.finished_at,
            output_excerpt=result.output_excerpt,
        )
    return 1
