"""Pydantic contracts for the local review-console API."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class VerificationRequest(BaseModel):
    status: Literal[
        "passed",
        "partially_passed",
        "failed",
        "timed_out",
        "error",
        "inconclusive",
        "skipped",
    ]
    verification_method: Literal["automated", "manual", "not_verifiable"] = "manual"
    check_type: Literal["test", "build", "lint", "behavior", "research", "other"] = "other"
    command: str = ""
    exit_code: int | None = None
    duration_ms: int | None = Field(default=None, ge=0)
    commit: str | None = None
    output: str | None = None


class VerificationResponse(BaseModel):
    recorded: bool
    run: dict[str, Any] | None = None


class ConversationSummary(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: str
    conversation_id: str
    status: str | None = None
    repository_root: str | None = None
    prompt_preview: str | None = None
    models: list[str] = Field(default_factory=list)
    categories: list[str] = Field(default_factory=list)
    router_checks: dict[str, int] = Field(default_factory=dict)
    human_evidence_count: int = 0
    needs_review: bool = False
    started_at: Any = None
    updated_at: Any = None
    finished_at: Any = None


class ConversationDetail(BaseModel):
    model_config = ConfigDict(extra="allow")

    task_id: str
    conversation_id: str
    task: dict[str, Any]
    generations: list[dict[str, Any]] = Field(default_factory=list)
    outcome_signals: list[dict[str, Any]] = Field(default_factory=list)
    verification_runs: list[dict[str, Any]] = Field(default_factory=list)
    verification_trusted: bool = False
