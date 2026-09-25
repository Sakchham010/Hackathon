"""Optional asynchronous LLM classification, used only when rules are unsure.

Disabled by default (see ``ClassificationConfig.llm_enabled``). The rules
result is always computed and stored regardless of whether a provider runs,
so the two can be compared later. This module defines the provider contract;
teams wire in their own HTTP endpoint via :class:`HttpClassificationProvider`
rather than this project depending on any one vendor's SDK.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from cursor_model_router.classification.features import ActivityFeatures


@dataclass(frozen=True)
class LLMClassificationResult:
    category: str
    subcategory: str | None
    primary_language: str | None
    intent: str | None
    cross_file_scope: bool | None
    complexity: str | None
    confidence: float
    evidence: dict[str, Any]
    provider: str
    provider_model: str
    prompt_version: str


class ClassificationProvider(ABC):
    @abstractmethod
    async def classify(
        self, *, prompt_text: str, activity: ActivityFeatures
    ) -> LLMClassificationResult | None:
        """Return a classification, or None if the provider could not classify.

        ``prompt_text`` is the generation's own prompt (intent); ``activity``
        is observed evidence from that same generation. Providers should keep
        the same separation the rules classifier does and not let activity
        override what the prompt says was requested.
        """


class HttpClassificationProvider(ClassificationProvider):
    """Posts prompt text and extracted features to a configured HTTP endpoint.

    The endpoint is expected to return a JSON body matching the
    :class:`LLMClassificationResult` fields (minus ``provider``/``provider_model``/
    ``prompt_version``, which come from configuration). Any transport or
    parsing failure returns ``None`` so the caller keeps the rules result.
    """

    def __init__(
        self, *, endpoint_url: str, model: str, prompt_version: str, timeout_seconds: float = 20.0
    ) -> None:
        self._endpoint_url = endpoint_url
        self._model = model
        self._prompt_version = prompt_version
        self._timeout_seconds = timeout_seconds

    async def classify(
        self, *, prompt_text: str, activity: ActivityFeatures
    ) -> LLMClassificationResult | None:
        try:
            import httpx
        except ImportError:
            return None

        payload = {
            "prompt": prompt_text,
            "model_version": self._model,
            "prompt_version": self._prompt_version,
            # Observed activity/outcome evidence, kept separate from the
            # prompt so the endpoint can weigh it the same way the rules
            # classifier does: never as a substitute for stated intent.
            "activity": {
                "touched_file_count": len(set(activity.touched_files)),
                "languages": dict(activity.languages),
                "tool_call_count": activity.tool_call_count,
                "edit_count": activity.edit_count,
                "saw_build_command": activity.saw_build_command,
                "saw_test_command": activity.saw_test_command,
                "had_tool_failure": activity.had_tool_failure,
                "failure_count": activity.failure_count,
                "saw_stack_trace": activity.saw_stack_trace,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(self._endpoint_url, json=payload)
                response.raise_for_status()
                body = response.json()
        except (httpx.HTTPError, ValueError):
            return None

        try:
            return LLMClassificationResult(
                category=body["category"],
                subcategory=body.get("subcategory"),
                primary_language=body.get("primary_language"),
                intent=body.get("intent"),
                cross_file_scope=body.get("cross_file_scope"),
                complexity=body.get("complexity"),
                confidence=float(body.get("confidence", 0.0)),
                evidence=body.get("evidence", {}),
                provider="http",
                provider_model=self._model,
                prompt_version=self._prompt_version,
            )
        except (KeyError, TypeError, ValueError):
            return None


class NullClassificationProvider(ClassificationProvider):
    async def classify(
        self, *, prompt_text: str, activity: ActivityFeatures
    ) -> LLMClassificationResult | None:
        return None
