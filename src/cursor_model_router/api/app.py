"""FastAPI application for the localhost review console."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from cursor_model_router.api.models import (
    ConversationDetail,
    ConversationSummary,
    VerificationRequest,
    VerificationResponse,
)
from cursor_model_router.api.queries import ReviewQueries, json_safe
from cursor_model_router.common.config import RouterConfig, load_config
from cursor_model_router.common.constants import TaskStatus
from cursor_model_router.database.client import create_async_client, create_sync_client
from cursor_model_router.outcomes.ingestion import record_user_submitted_result_sync
from cursor_model_router.verification.worker import run_checks_for_task

FilterName = Literal["needs_review", "in_progress", "has_human_evidence", "all"]


def create_app(
    config: RouterConfig | None = None,
    *,
    database=None,
) -> FastAPI:
    config = config or load_config()
    app = FastAPI(title="Cursor Model Router Review Console", version="0.1.0")
    app.state.config = config
    app.state.database = database
    app.state.client = None

    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["Content-Type"],
    )

    def queries() -> ReviewQueries:
        if app.state.database is None:
            app.state.client = app.state.client or create_sync_client(config)
            app.state.database = app.state.client[config.database_name]
        return ReviewQueries(app.state.database, config)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/conversations", response_model=list[ConversationSummary])
    def list_conversations(
        filter: FilterName = Query("needs_review"),
        limit: int = Query(100, ge=1, le=200),
    ) -> list[dict]:
        rows = queries().list_conversations(filter_name=filter, limit=limit)
        return [json_safe(row) for row in rows]

    @app.get("/api/conversations/{identifier}", response_model=ConversationDetail)
    def get_conversation(identifier: str) -> dict:
        result = queries().get_conversation(identifier)
        if result is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return json_safe(result)

    @app.post(
        "/api/conversations/{identifier}/verification",
        response_model=VerificationResponse,
        status_code=201,
    )
    def record_verification(
        identifier: str, request: VerificationRequest
    ) -> dict[str, object]:
        reader = queries()
        task = reader.resolve_task(identifier)
        if task is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        document = record_user_submitted_result_sync(
            reader.database,
            task_id=str(task["_id"]),
            status=request.status,
            verification_method=request.verification_method,
            check_type=request.check_type,
            command=request.command,
            exit_code=request.exit_code,
            duration_ms=request.duration_ms,
            commit=request.commit,
            output=request.output,
            max_output_chars=config.redaction.max_command_output_chars,
        )
        return {"recorded": document is not None, "run": json_safe(document)}

    @app.post("/api/conversations/{identifier}/verification/run")
    async def run_verification(identifier: str) -> dict[str, object]:
        reader = queries()
        task = reader.resolve_task(identifier)
        if task is None:
            raise HTTPException(status_code=404, detail="Conversation not found")
        if task.get("status") not in {
            TaskStatus.COMPLETED,
            TaskStatus.ABORTED,
            TaskStatus.ERROR,
        }:
            raise HTTPException(status_code=409, detail="Conversation is not finished")

        client = create_async_client(config)
        try:
            count = await run_checks_for_task(
                client[config.database_name],
                config,
                task,
            )
        finally:
            await client.close()
        return {"processed": count, "conversation_id": task["conversation_id"]}

    web_dist = Path(__file__).resolve().parents[3] / "web" / "dist"
    if web_dist.is_dir():
        @app.get("/{path:path}", include_in_schema=False)
        def serve_web(path: str):
            if path.startswith("api/"):
                raise HTTPException(status_code=404, detail="Not found")
            requested_file = web_dist / path
            if requested_file.is_file():
                return FileResponse(requested_file)
            return FileResponse(web_dist / "index.html")

    return app
