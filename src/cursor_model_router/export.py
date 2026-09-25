"""Flatten collected data into one analysis-ready row per conversation.

Intentionally does not compute or emit a "best model" recommendation - the
MVP's job is to make the raw, joined observational data available for
external analysis, not to draw conclusions from it.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from bson.json_util import default as bson_json_default
from pymongo.database import Database

from cursor_model_router.common.constants import CollectionNames


def _index_by_field(rows: list[dict[str, Any]], field_name: str) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(row[field_name], []).append(row)
    return grouped


def _index_by_task(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    return _index_by_field(rows, "task_id")


def build_export_rows(database: Database) -> Iterator[dict[str, Any]]:
    """Yield one row per conversation task, with its generations nested beneath it.

    ``task_generations`` and generation-scoped ``outcome_signals`` are grouped
    by ``task_id`` (the conversation-level id they carry). ``task_classifications``
    is grouped by ``generation_task_id`` instead, since that -- not ``task_id`` --
    is what uniquely identifies the generation a classification belongs to; each
    generation row ends up carrying only its own prompt, classification, and
    outcome evidence, never another turn's.
    """
    generations_by_task = _index_by_task(
        list(database[CollectionNames.TASK_GENERATIONS].find({}))
    )
    classifications_by_generation = _index_by_field(
        list(database[CollectionNames.TASK_CLASSIFICATIONS].find({})), "generation_task_id"
    )
    # Keyed by whatever task_id each signal was recorded against: a
    # conversation task id for conversation-level signals (agent_status,
    # follow_up_generation), or a generation task id for generation-level
    # signals (tool_failure, shell_exit, build_test_activity).
    signals_by_key = _index_by_task(list(database[CollectionNames.OUTCOME_SIGNALS].find({})))
    runs_by_task = _index_by_task(list(database[CollectionNames.VERIFICATION_RUNS].find({})))

    for task in database[CollectionNames.TASKS].find({}):
        task_id = task["_id"]
        conversation_id = task["conversation_id"]

        generation_rows = []
        for generation in generations_by_task.get(task_id, []):
            generation_task_id = generation["_id"]
            generation_rows.append(
                {
                    "generation_task_id": generation_task_id,
                    "generation_id": generation.get("generation_id"),
                    "generation": generation,
                    "classifications": classifications_by_generation.get(
                        generation_task_id, []
                    ),
                    "outcome_signals": signals_by_key.get(generation_task_id, []),
                }
            )

        yield {
            "task_id": task_id,
            "conversation_id": conversation_id,
            "task": task,
            "generations": generation_rows,
            "outcome_signals": signals_by_key.get(task_id, []),
            "verification_runs": runs_by_task.get(task_id, []),
        }


def export_jsonl(database: Database, output_path: Path) -> int:
    count = 0
    with output_path.open("w", encoding="utf-8") as handle:
        for row in build_export_rows(database):
            handle.write(json.dumps(row, default=bson_json_default))
            handle.write("\n")
            count += 1
    return count


def export_parquet(database: Database, output_path: Path) -> int:
    try:
        import pandas as pd
    except ImportError as exc:
        raise RuntimeError(
            "Parquet export requires the optional 'pandas'/'pyarrow' dependencies. "
            "Install them or use --format jsonl instead."
        ) from exc

    rows = list(build_export_rows(database))
    frame = pd.json_normalize(rows, sep=".")
    frame.to_parquet(output_path)
    return len(rows)
