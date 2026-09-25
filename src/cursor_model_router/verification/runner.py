"""Execute a single trusted verification command and report its result.

Always runs in a background worker process, never inside a Cursor hook.
Output is redacted and truncated before it is returned so secrets in build
logs never reach MongoDB.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from cursor_model_router.common.constants import VerificationRunStatus
from cursor_model_router.common.redaction import sanitize_free_text
from cursor_model_router.common.time_utils import utc_now
from cursor_model_router.verification.repo_config import CheckDefinition


@dataclass(frozen=True)
class CheckExecutionResult:
    status: str
    exit_code: int | None
    duration_ms: int
    started_at: datetime
    finished_at: datetime
    output_excerpt: str | None


def run_check(
    check: CheckDefinition,
    *,
    repo_root: Path,
    effective_timeout_seconds: int,
    max_output_chars: int,
) -> CheckExecutionResult:
    working_directory = (repo_root / check.working_directory).resolve()
    started_at = utc_now()

    try:
        completed = subprocess.run(
            check.command,
            shell=True,
            cwd=working_directory,
            capture_output=True,
            text=True,
            timeout=effective_timeout_seconds,
            check=False,
        )
        finished_at = utc_now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        status = (
            VerificationRunStatus.PASSED
            if completed.returncode == 0
            else VerificationRunStatus.FAILED
        )
        combined_output = (completed.stdout or "") + (completed.stderr or "")
        return CheckExecutionResult(
            status=status,
            exit_code=completed.returncode,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            output_excerpt=sanitize_free_text(combined_output, max_output_chars),
        )
    except subprocess.TimeoutExpired as exc:
        finished_at = utc_now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        combined_output = (
            (exc.stdout or "") + (exc.stderr or "") if isinstance(exc.stdout, str) else ""
        )
        return CheckExecutionResult(
            status=VerificationRunStatus.TIMED_OUT,
            exit_code=None,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            output_excerpt=sanitize_free_text(combined_output, max_output_chars) or None,
        )
    except OSError as exc:
        finished_at = utc_now()
        duration_ms = int((finished_at - started_at).total_seconds() * 1000)
        return CheckExecutionResult(
            status=VerificationRunStatus.ERROR,
            exit_code=None,
            duration_ms=duration_ms,
            started_at=started_at,
            finished_at=finished_at,
            output_excerpt=sanitize_free_text(str(exc), max_output_chars),
        )
