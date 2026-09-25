"""Asynchronous classification worker.

Runs outside the hook process entirely (invoked via ``router classify
pending``, or on a schedule such as cron/Task Scheduler). Classifies one
generation task at a time: category/intent come only from that generation's
own prompt, and complexity/scope/evidence come only from that generation's
own events, so later activity in the same or a later generation never
changes an already-classified generation. Always writes the deterministic
rules result; only calls an LLM provider when rules confidence is below the
configured threshold and a provider is enabled, so classification stays
cheap by default.
"""

from __future__ import annotations

import logging

from pymongo.asynchronous.database import AsyncDatabase

from cursor_model_router.classification.features import (
    extract_activity_features,
    extract_prompt_features,
)
from cursor_model_router.classification.providers import (
    ClassificationProvider,
    NullClassificationProvider,
)
from cursor_model_router.classification.rules import classify as classify_with_rules
from cursor_model_router.common.config import RouterConfig
from cursor_model_router.common.constants import ClassificationSource
from cursor_model_router.database.documents import build_classification_document
from cursor_model_router.database.repositories import ClassificationRepositoryAsync, TaskReaderAsync

logger = logging.getLogger(__name__)


async def classify_batch(
    database: AsyncDatabase,
    config: RouterConfig,
    *,
    limit: int = 200,
    provider: ClassificationProvider | None = None,
) -> int:
    provider = provider or NullClassificationProvider()

    reader = TaskReaderAsync(database)
    classifications = ClassificationRepositoryAsync(database)

    processed = 0
    async for generation in reader.find_finished_generations_without_classification(limit=limit):
        generation_task_id = generation["_id"]
        events = await reader.find_events_for_generation(
            task_id=generation["task_id"], generation_id=generation["generation_id"]
        )
        prompt = extract_prompt_features(generation)
        activity = extract_activity_features(events)
        result = classify_with_rules(prompt, activity)

        rules_document = build_classification_document(
            task_id=generation["task_id"],
            generation_task_id=generation_task_id,
            source=ClassificationSource.RULES,
            model=generation.get("model"),
            model_id=generation.get("model_id"),
            repository_root=generation.get("repository_root"),
            category=result.category,
            subcategory=result.subcategory,
            primary_language=result.primary_language,
            intent=result.intent,
            cross_file_scope=result.cross_file_scope,
            complexity=result.complexity,
            confidence=result.confidence,
            evidence=result.evidence,
        )
        await classifications.upsert_classification(rules_document)
        processed += 1

        low_confidence = result.confidence < config.classification.low_confidence_threshold
        if config.classification.llm_enabled and low_confidence:
            try:
                llm_result = await provider.classify(
                    prompt_text=prompt.prompt_text, activity=activity
                )
            except Exception:
                logger.exception(
                    "LLM classification provider failed for generation %s", generation_task_id
                )
                llm_result = None

            if llm_result is not None:
                llm_document = build_classification_document(
                    task_id=generation["task_id"],
                    generation_task_id=generation_task_id,
                    source=ClassificationSource.LLM,
                    model=generation.get("model"),
                    model_id=generation.get("model_id"),
                    repository_root=generation.get("repository_root"),
                    category=llm_result.category,
                    subcategory=llm_result.subcategory,
                    primary_language=llm_result.primary_language,
                    intent=llm_result.intent,
                    cross_file_scope=llm_result.cross_file_scope,
                    complexity=llm_result.complexity,
                    confidence=llm_result.confidence,
                    evidence=llm_result.evidence,
                    provider=llm_result.provider,
                    provider_model=llm_result.provider_model,
                    prompt_version=llm_result.prompt_version,
                )
                await classifications.upsert_classification(llm_document)

    return processed
