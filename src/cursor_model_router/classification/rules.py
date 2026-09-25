"""Deterministic, keyword-based task classifier.

Category, subcategory, and intent are derived *only* from the generation's
own prompt text (:class:`~cursor_model_router.classification.features.PromptFeatures`).
Observed activity (:class:`~cursor_model_router.classification.features.ActivityFeatures`)
-- edits, tool calls, commands, failures -- never changes what a request is
classified as; it only ever appears as evidence alongside the classification
(``cross_file_scope``, ``complexity``, and the ``evidence`` dict). A tool
failure is outcome evidence about how a generation went, not a signal about
what the user asked for, so it must never make an otherwise-feature prompt
look like a debugging request.

Deterministic and keyword-based on purpose: it must be cheap enough to run on
every finished generation, and its evidence must be inspectable so
classification mistakes can be diagnosed without guessing what an LLM
"meant".
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from cursor_model_router.classification.features import ActivityFeatures, PromptFeatures
from cursor_model_router.classification.taxonomy import (
    CATEGORY_DEBUGGING_KEYWORDS,
    CATEGORY_FEATURE_KEYWORDS,
    CATEGORY_REFACTOR_KEYWORDS,
    CATEGORY_SIMPLE_EDIT_KEYWORDS,
    DOMAIN_KEYWORDS,
)

_INTENT_BY_CATEGORY = {
    "debugging": "fix",
    "feature": "implement",
    "refactor": "restructure",
    "simple_edit": "edit",
    "unknown": None,
}

_CATEGORY_KEYWORDS: dict[str, tuple[str, ...]] = {
    "debugging": CATEGORY_DEBUGGING_KEYWORDS,
    "feature": CATEGORY_FEATURE_KEYWORDS,
    "refactor": CATEGORY_REFACTOR_KEYWORDS,
    "simple_edit": CATEGORY_SIMPLE_EDIT_KEYWORDS,
}

_LOW_COMPLEXITY_MAX_FILES = 1
_MEDIUM_COMPLEXITY_MAX_FILES = 4

# Strip fenced/inline code (the most common way a pasted stack trace, log, or
# quoted assistant/error text ends up inside a user prompt) before scanning
# for category/domain keywords, so quoted content is never mistaken for the
# user's own words.
_FENCED_CODE_BLOCK = re.compile(r"```.*?```", re.DOTALL)
_INLINE_CODE = re.compile(r"`[^`]*`")


@dataclass(frozen=True)
class ClassificationResult:
    category: str
    subcategory: str | None
    primary_language: str | None
    intent: str | None
    cross_file_scope: bool
    complexity: str
    confidence: float
    evidence: dict[str, Any]


def _strip_quoted_content(text: str) -> str:
    text = _FENCED_CODE_BLOCK.sub(" ", text)
    text = _INLINE_CODE.sub(" ", text)
    return text


def _keyword_pattern(keyword: str) -> re.Pattern[str]:
    # Word-boundary match so e.g. "fix" does not match inside "prefix", and
    # "add" does not match inside "address"; phrases with spaces (e.g.
    # "stack trace") still match as a literal run of words.
    return re.compile(r"(?<!\w)" + re.escape(keyword) + r"(?!\w)", re.IGNORECASE)


def _count_keyword_hits(text: str, keywords: tuple[str, ...]) -> list[str]:
    return [keyword for keyword in keywords if _keyword_pattern(keyword).search(text)]


def _classify_category(prompt: PromptFeatures) -> tuple[str, float, dict[str, list[str]]]:
    scannable_text = _strip_quoted_content(prompt.prompt_text)
    hits_by_category = {
        category: _count_keyword_hits(scannable_text, keywords)
        for category, keywords in _CATEGORY_KEYWORDS.items()
    }
    scored = {category: len(hits) for category, hits in hits_by_category.items()}

    ranked = sorted(scored.values(), reverse=True)
    best_score = ranked[0] if ranked else 0
    second_score = ranked[1] if len(ranked) > 1 else 0

    if best_score == 0:
        return "unknown", 0.2, hits_by_category

    leaders = [category for category, score in scored.items() if score == best_score]
    if len(leaders) > 1:
        # An explicit, low-confidence tie beats silently picking whichever
        # category happens to come first in _CATEGORY_KEYWORDS.
        return "unknown", 0.3, hits_by_category

    margin = best_score - second_score
    confidence = min(0.5 + 0.1 * best_score + 0.05 * margin, 0.95)
    return leaders[0], confidence, hits_by_category


def _classify_domain(prompt: PromptFeatures) -> tuple[str | None, list[str]]:
    scannable_text = _strip_quoted_content(prompt.prompt_text)
    best_domain: str | None = None
    best_hits: list[str] = []
    for domain, keywords in DOMAIN_KEYWORDS.items():
        hits = _count_keyword_hits(scannable_text, keywords)
        if len(hits) > len(best_hits):
            best_domain, best_hits = domain, hits
    return best_domain, best_hits


def _classify_complexity(activity: ActivityFeatures) -> str:
    file_count = len(set(activity.touched_files))
    if file_count <= _LOW_COMPLEXITY_MAX_FILES and activity.tool_call_count <= 5:
        return "low"
    if file_count <= _MEDIUM_COMPLEXITY_MAX_FILES:
        return "medium"
    return "high"


def classify(prompt: PromptFeatures, activity: ActivityFeatures) -> ClassificationResult:
    category, category_confidence, category_hits = _classify_category(prompt)
    domain, domain_hits = _classify_domain(prompt)

    primary_language = activity.languages.most_common(1)[0][0] if activity.languages else None
    cross_file_scope = len(set(activity.touched_files)) > 1
    complexity = _classify_complexity(activity)
    intent = _INTENT_BY_CATEGORY.get(category)

    evidence = {
        "category_keyword_hits": category_hits,
        "domain_keyword_hits": domain_hits,
        "touched_file_count": len(set(activity.touched_files)),
        "unique_directories": activity.unique_directories,
        "tool_call_count": activity.tool_call_count,
        "edit_count": activity.edit_count,
        "saw_build_command": activity.saw_build_command,
        "saw_test_command": activity.saw_test_command,
        "languages": dict(activity.languages),
        # Outcome evidence only: never used to choose category/intent above.
        "had_tool_failure": activity.had_tool_failure,
        "failure_count": activity.failure_count,
        "saw_stack_trace": activity.saw_stack_trace,
    }

    return ClassificationResult(
        category=category,
        subcategory=domain,
        primary_language=primary_language,
        intent=intent,
        cross_file_scope=cross_file_scope,
        complexity=complexity,
        confidence=category_confidence,
        evidence=evidence,
    )
