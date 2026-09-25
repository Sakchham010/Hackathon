"""``router`` command-line interface.

Thin wiring layer: every command loads config, opens the appropriate client
flavor (sync for one-off reads/writes, async for the polling workers), calls
into the relevant module, and reports a human-readable summary.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import typer

from cursor_model_router.classification.worker import classify_batch
from cursor_model_router.collector.hook import read_hook_payload
from cursor_model_router.collector.install import install_user_hooks, uninstall_user_hooks
from cursor_model_router.collector.service import drain, handle_raw_event
from cursor_model_router.common.config import RouterConfig, load_config
from cursor_model_router.common.constants import ExitCode
from cursor_model_router.database.client import create_async_client, create_sync_client
from cursor_model_router.database.schema import initialize_schema
from cursor_model_router.export import export_jsonl, export_parquet
from cursor_model_router.outcomes.ingestion import (
    InvalidVerificationValue,
    record_user_submitted_result,
)
from cursor_model_router.outcomes.worker import extract_signals_batch
from cursor_model_router.verification.worker import run_pending_checks

app = typer.Typer(help="Passive Cursor Agent telemetry, classification, and outcome collection.")
db_app = typer.Typer(help="Database schema management.")
hooks_app = typer.Typer(help="Install/uninstall the router's Cursor hooks.")
classify_app = typer.Typer(help="Run task classification.")
outcome_app = typer.Typer(help="Outcome signals and user-submitted verification results.")
verification_app = typer.Typer(help="Repository-defined verification checks.")
spool_app = typer.Typer(help="Local spool used when MongoDB is unreachable.")

app.add_typer(db_app, name="db")
app.add_typer(hooks_app, name="hooks")
app.add_typer(classify_app, name="classify")
app.add_typer(outcome_app, name="outcome")
app.add_typer(verification_app, name="verification")
app.add_typer(spool_app, name="spool")


def _load_config() -> RouterConfig:
    return load_config()


def _run_async(factory) -> None:
    asyncio.run(factory())


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", help="Bind address. Loopback is the safe default."),
    port: int = typer.Option(8787, min=1, max=65535),
    reload: bool = typer.Option(
        True,
        "--reload/--no-reload",
        help="Reload the API when Python sources change.",
    ),
) -> None:
    """Start the local React review console API."""
    try:
        import uvicorn
    except ImportError as exc:
        typer.echo('Install the web extra with: pip install -e ".[web]"', err=True)
        raise typer.Exit(code=ExitCode.CONFIG_ERROR) from exc

    # Reload requires an import string, not an app instance. Watch only this
    # package so web/node_modules and .venv do not trigger restarts.
    run_kwargs: dict[str, object] = {
        "app": "cursor_model_router.api.app:create_app",
        "factory": True,
        "host": host,
        "port": port,
        "reload": reload,
    }
    if reload:
        run_kwargs["reload_dirs"] = [str(Path(__file__).resolve().parent)]
    uvicorn.run(**run_kwargs)


@app.command()
def hook() -> None:
    """Read one Cursor hook payload from stdin and respond on stdout.

    This is the command installed into ``hooks.json``; it is not meant to be
    run interactively.
    """
    raw = read_hook_payload(sys.stdin)

    try:
        config = _load_config()
        response = handle_raw_event(raw, config)
    except Exception:  # noqa: BLE001 - never let this surface as a blocked hook
        response = {}

    sys.stdout.write(json.dumps(response))


@db_app.command("initialize")
def db_initialize() -> None:
    """Create/update MongoDB indexes. Safe to run repeatedly."""
    config = _load_config()
    client = create_sync_client(config)
    try:
        initialize_schema(client, config.database_name)
    finally:
        client.close()
    typer.echo(f"Initialized schema on database '{config.database_name}'.")


@hooks_app.command("install")
def hooks_install() -> None:
    path = install_user_hooks()
    typer.echo(f"Installed router hooks into {path}")


@hooks_app.command("uninstall")
def hooks_uninstall() -> None:
    path = uninstall_user_hooks()
    typer.echo(f"Removed router hooks from {path}")


@spool_app.command("drain")
def spool_drain() -> None:
    config = _load_config()
    count = drain(config)
    typer.echo(f"Drained {count} spooled event(s).")


@classify_app.command("pending")
def classify_pending(
    limit: int = typer.Option(200, help="Maximum finished generations to classify in this batch."),
) -> None:
    config = _load_config()

    async def _run() -> None:
        client = create_async_client(config)
        try:
            database = client[config.database_name]
            processed = await classify_batch(database, config, limit=limit)
            typer.echo(f"Classified {processed} generation(s).")
        finally:
            await client.close()

    _run_async(_run)


@outcome_app.command("extract-signals")
def outcome_extract_signals(limit: int = typer.Option(200)) -> None:
    config = _load_config()

    async def _run() -> None:
        client = create_async_client(config)
        try:
            database = client[config.database_name]
            processed = await extract_signals_batch(database, limit=limit)
            typer.echo(f"Extracted signals for {processed} task(s).")
        finally:
            await client.close()

    _run_async(_run)


@outcome_app.command("record")
def outcome_record(
    task_id: str = typer.Option(...),
    status: str = typer.Option(
        ...,
        help="One of: passed, partially_passed, failed, timed_out, error, inconclusive, skipped",
    ),
    verification_method: str = typer.Option(
        "manual", help="One of: automated, manual, not_verifiable"
    ),
    check_type: str = typer.Option(
        "other", help="One of: test, build, lint, behavior, research, other"
    ),
    command: str = typer.Option("", help="Command or test path associated with this evidence."),
    exit_code: int | None = typer.Option(None),
    duration_ms: int | None = typer.Option(None),
    commit: str | None = typer.Option(None),
    output: str | None = typer.Option(None),
) -> None:
    config = _load_config()

    async def _run() -> None:
        client = create_async_client(config)
        try:
            database = client[config.database_name]
            try:
                inserted = await record_user_submitted_result(
                    database,
                    task_id=task_id,
                    status=status,
                    verification_method=verification_method,
                    check_type=check_type,
                    command=command,
                    exit_code=exit_code,
                    duration_ms=duration_ms,
                    commit=commit,
                    output=output,
                    max_output_chars=config.redaction.max_command_output_chars,
                )
            except InvalidVerificationValue as exc:
                typer.echo(str(exc), err=True)
                raise typer.Exit(code=ExitCode.CONFIG_ERROR) from exc
            typer.echo("Recorded." if inserted else "Not recorded.")
        finally:
            await client.close()

    _run_async(_run)


@verification_app.command("run-pending")
def verification_run_pending(limit: int = typer.Option(100)) -> None:
    config = _load_config()

    async def _run() -> None:
        client = create_async_client(config)
        try:
            database = client[config.database_name]
            processed = await run_pending_checks(database, config, limit=limit)
            typer.echo(f"Processed verification for {processed} task(s).")
        finally:
            await client.close()

    _run_async(_run)


@app.command()
def export(
    output: Path = typer.Option(..., help="Output file path."),
    format: str = typer.Option("jsonl", help="jsonl or parquet"),
) -> None:
    config = _load_config()
    client = create_sync_client(config)
    try:
        database = client[config.database_name]
        if format == "jsonl":
            count = export_jsonl(database, output)
        elif format == "parquet":
            count = export_parquet(database, output)
        else:
            typer.echo(f"Unsupported format: {format}", err=True)
            raise typer.Exit(code=ExitCode.CONFIG_ERROR)
        typer.echo(f"Exported {count} conversation(s) to {output}")
    finally:
        client.close()


if __name__ == "__main__":
    app()
