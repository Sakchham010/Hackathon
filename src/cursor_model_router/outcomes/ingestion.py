"""User/CI-submitted verification results.

Lets a repository's own test suite, a CI job, or a person tell the router
"this task's change passed/failed this check" after the Cursor conversation
itself has ended. Distinct from router-executed verification: results are
attributed with
``source=user_submitted`` so later analysis never conflates the two.
"""

from __future__ import annotations

from datetime import datetime

from pymongo.asynchronous.database import AsyncDatabase
from pymongo.database import Database
from pymongo.errors import DuplicateKeyError

from cursor_model_router.common.constants import (
    CollectionNames,
    OutcomeSource,
    VerificationCheckType,
    VerificationMethod,
    VerificationRunStatus,
)
from cursor_model_router.common.redaction import sanitize_free_text
from cursor_model_router.common.time_utils import utc_now
from cursor_model_router.database.documents import build_verification_run
from cursor_model_router.database.repositories import VerificationRepositoryAsync

_VALID_STATUSES = {
    VerificationRunStatus.PASSED,
    VerificationRunStatus.PARTIALLY_PASSED,
    VerificationRunStatus.FAILED,
    VerificationRunStatus.TIMED_OUT,
    VerificationRunStatus.ERROR,
    VerificationRunStatus.INCONCLUSIVE,
    VerificationRunStatus.SKIPPED,
}
_VALID_METHODS = {
    VerificationMethod.AUTOMATED,
    VerificationMethod.MANUAL,
    VerificationMethod.NOT_VERIFIABLE,
}
_VALID_CHECK_TYPES = {
    VerificationCheckType.TEST,
    VerificationCheckType.BUILD,
    VerificationCheckType.LINT,
    VerificationCheckType.BEHAVIOR,
    VerificationCheckType.RESEARCH,
    VerificationCheckType.OTHER,
}


class InvalidVerificationValue(ValueError):
    pass


class InvalidVerificationStatus(InvalidVerificationValue):
    pass


async def record_user_submitted_result(
    database: AsyncDatabase,
    *,
    task_id: str,
    status: str,
    verification_method: str = VerificationMethod.MANUAL,
    check_type: str = VerificationCheckType.OTHER,
    command: str = "",
    exit_code: int | None = None,
    duration_ms: int | None = None,
    commit: str | None = None,
    output: str | None = None,
    max_output_chars: int = 4000,
    occurred_at: datetime | None = None,
) -> bool:
    if status not in _VALID_STATUSES:
        raise InvalidVerificationStatus(
            f"status must be one of {sorted(_VALID_STATUSES)}, got {status!r}"
        )
    if verification_method not in _VALID_METHODS:
        raise InvalidVerificationValue(
            f"verification_method must be one of {sorted(_VALID_METHODS)}, "
            f"got {verification_method!r}"
        )
    if check_type not in _VALID_CHECK_TYPES:
        raise InvalidVerificationValue(
            f"check_type must be one of {sorted(_VALID_CHECK_TYPES)}, got {check_type!r}"
        )

    timestamp = occurred_at or utc_now()

    document = build_verification_run(
        task_id=task_id,
        verification_method=verification_method,
        check_type=check_type,
        command=command,
        status=status,
        exit_code=exit_code,
        duration_ms=duration_ms,
        started_at=timestamp,
        finished_at=timestamp,
        commit=commit,
        working_tree_dirty=None,
        output_excerpt=sanitize_free_text(output, max_output_chars),
        source=OutcomeSource.USER_SUBMITTED,
    )

    repository = VerificationRepositoryAsync(database)
    return (await repository.record_run(document)) is not None


def _validate_verification_values(
    *, status: str, verification_method: str, check_type: str
) -> None:
    if status not in _VALID_STATUSES:
        raise InvalidVerificationStatus(
            f"status must be one of {sorted(_VALID_STATUSES)}, got {status!r}"
        )
    if verification_method not in _VALID_METHODS:
        raise InvalidVerificationValue(
            f"verification_method must be one of {sorted(_VALID_METHODS)}, "
            f"got {verification_method!r}"
        )
    if check_type not in _VALID_CHECK_TYPES:
        raise InvalidVerificationValue(
            f"check_type must be one of {sorted(_VALID_CHECK_TYPES)}, got {check_type!r}"
        )


def record_user_submitted_result_sync(
    database: Database,
    *,
    task_id: str,
    status: str,
    verification_method: str = VerificationMethod.MANUAL,
    check_type: str = VerificationCheckType.OTHER,
    command: str = "",
    exit_code: int | None = None,
    duration_ms: int | None = None,
    commit: str | None = None,
    output: str | None = None,
    max_output_chars: int = 4000,
    occurred_at: datetime | None = None,
) -> dict | None:
    """Record UI/CI evidence using the same contract as the async CLI path."""
    _validate_verification_values(
        status=status,
        verification_method=verification_method,
        check_type=check_type,
    )
    timestamp = occurred_at or utc_now()
    document = build_verification_run(
        task_id=task_id,
        verification_method=verification_method,
        check_type=check_type,
        command=command,
        status=status,
        exit_code=exit_code,
        duration_ms=duration_ms,
        started_at=timestamp,
        finished_at=timestamp,
        commit=commit,
        working_tree_dirty=None,
        output_excerpt=sanitize_free_text(output, max_output_chars),
        source=OutcomeSource.USER_SUBMITTED,
    )
    try:
        result = database[CollectionNames.VERIFICATION_RUNS].insert_one(document)
    except DuplicateKeyError:
        return None
    document["_id"] = result.inserted_id
    return document
