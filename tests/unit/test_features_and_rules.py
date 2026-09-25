from cursor_model_router.classification.features import (
    extract_activity_features,
    extract_prompt_features,
)
from cursor_model_router.classification.rules import classify


def _event(event_type, **kwargs):
    event = {"event_type": event_type}
    event.update(kwargs)
    return event


def _generation(prompt_preview: str) -> dict:
    return {"prompt_preview": prompt_preview}


# --- extract_prompt_features -------------------------------------------------


def test_extract_prompt_features_uses_only_this_generations_prompt():
    generation = _generation("Fix this deadlock in the worker pool")

    prompt = extract_prompt_features(generation)

    assert prompt.prompt_text == "Fix this deadlock in the worker pool"
    assert prompt.prompt_length == len(prompt.prompt_text)


def test_extract_prompt_features_defaults_to_empty_when_missing():
    prompt = extract_prompt_features({})

    assert prompt.prompt_text == ""
    assert prompt.prompt_length == 0


# --- extract_activity_features ------------------------------------------------


def test_activity_features_counts_edits_and_languages_from_edits_only():
    events = [
        _event("pre_tool_use", tool_name="Shell", command="dotnet build"),
        _event("post_tool_use", tool_name="Shell", command="dotnet test"),
        _event("after_file_edit", file_path="src/Worker.cs", metadata={"edit_count": 2}),
        _event("after_file_edit", file_path="src/Pool.cs", metadata={"edit_count": 3}),
    ]

    activity = extract_activity_features(events)

    # Sums the hook's actual reported edit count rather than one-per-event.
    assert activity.edit_count == 5
    assert activity.languages["csharp"] == 2
    assert activity.saw_build_command is True
    assert activity.saw_test_command is True
    assert len(set(activity.touched_files)) == 2


def test_activity_features_ignores_read_only_tool_accesses_for_scope():
    events = [
        # A file opened via a read-only tool call must never count as an
        # edit or contribute to touched-file scope/language.
        _event("pre_tool_use", tool_name="Read", file_path="src/Other.py"),
        _event("post_tool_use", tool_name="Read", file_path="src/Other.py"),
        _event("after_file_edit", file_path="src/Worker.cs"),
    ]

    activity = extract_activity_features(events)

    assert activity.touched_files == ["src/Worker.cs"]
    assert activity.edit_count == 1
    assert "python" not in activity.languages


def test_activity_features_counts_one_logical_tool_call_per_tool_use_id():
    events = [
        _event("pre_tool_use", metadata={"tool_use_id": "call-1"}),
        _event("post_tool_use", metadata={"tool_use_id": "call-1"}),
        _event("post_tool_use_failure", metadata={"tool_use_id": "call-2"}),
        _event("pre_tool_use", metadata={}),  # no id: counts on its own
    ]

    activity = extract_activity_features(events)

    assert activity.tool_call_count == 3


def test_activity_features_flags_tool_failure_and_stack_trace_from_error_message():
    events = [
        _event(
            "post_tool_use_failure",
            metadata={
                "error_message": "Unhandled exception: NullReferenceException stack trace at line 12"
            },
        )
    ]

    activity = extract_activity_features(events)

    assert activity.had_tool_failure is True
    assert activity.failure_count == 1
    assert activity.saw_stack_trace is True


# --- classify: category/intent come only from the prompt ---------------------


def test_classify_detects_debugging_category_from_prompt_alone():
    prompt = extract_prompt_features(_generation("Find and fix this multithreaded deadlock"))
    activity = extract_activity_features([])

    result = classify(prompt, activity)

    assert result.category == "debugging"
    assert result.subcategory == "concurrency"
    assert 0.0 < result.confidence <= 1.0


def test_classify_falls_back_to_unknown_without_keyword_matches():
    prompt = extract_prompt_features(_generation("hello there"))
    activity = extract_activity_features([])

    result = classify(prompt, activity)

    assert result.category == "unknown"
    assert result.confidence < 0.5


def test_classify_does_not_promote_to_debugging_from_a_tool_failure_alone():
    """A tool failure is outcome evidence, never category input."""
    prompt = extract_prompt_features(_generation("Please take a look at this for me"))
    activity = extract_activity_features(
        [
            _event(
                "post_tool_use_failure",
                metadata={"error_message": "Unhandled exception: stack trace at line 4"},
            )
        ]
    )

    result = classify(prompt, activity)

    assert result.category == "unknown"
    assert result.evidence["had_tool_failure"] is True
    assert result.evidence["saw_stack_trace"] is True


def test_classify_keeps_feature_category_despite_a_transient_failure():
    """A build/tool failure encountered while doing feature work must not flip intent."""
    prompt = extract_prompt_features(_generation("Add a new settings page to the app"))
    activity = extract_activity_features(
        [
            _event(
                "post_tool_use_failure",
                metadata={"error_message": "Unhandled exception: stack trace at line 4"},
            )
        ]
    )

    result = classify(prompt, activity)

    assert result.category == "feature"
    assert result.evidence["had_tool_failure"] is True


def test_classify_ignores_quoted_stack_trace_inside_the_prompt():
    """Pasted/fenced text in the prompt must not be scanned as the user's own words."""
    prompt_text = (
        "Add a retry helper for this call.\n"
        "```\n"
        "Traceback (most recent call last):\n"
        "  File x, line 1\n"
        "Exception: boom\n"
        "```"
    )
    prompt = extract_prompt_features(_generation(prompt_text))
    activity = extract_activity_features([])

    result = classify(prompt, activity)

    assert result.category == "feature"


def test_classify_uses_word_boundaries_to_avoid_substring_collisions():
    """"add" must not match inside "address"."""
    prompt = extract_prompt_features(_generation("Please address this concern in the doc"))
    activity = extract_activity_features([])

    result = classify(prompt, activity)

    assert result.category != "feature"


def test_classify_explicit_tie_is_unknown_with_low_confidence():
    prompt = extract_prompt_features(_generation("Fix and refactor this module"))
    activity = extract_activity_features([])

    result = classify(prompt, activity)

    assert result.category == "unknown"
    assert result.confidence <= 0.3
    assert result.evidence["category_keyword_hits"]["debugging"]
    assert result.evidence["category_keyword_hits"]["refactor"]


def test_classify_cross_file_scope_and_complexity_from_edits_only():
    prompt = extract_prompt_features(_generation("Refactor the payment module across files"))
    activity = extract_activity_features(
        [
            _event("pre_tool_use", file_path="ignored/read.py"),
            _event("after_file_edit", file_path="a.py"),
            _event("after_file_edit", file_path="b.py"),
            _event("after_file_edit", file_path="c.py"),
            _event("after_file_edit", file_path="d.py"),
            _event("after_file_edit", file_path="e.py"),
        ]
    )

    result = classify(prompt, activity)

    assert result.cross_file_scope is True
    assert result.complexity == "high"
    assert result.evidence["touched_file_count"] == 5


def test_classify_language_reflects_distinct_edited_files_not_event_count():
    prompt = extract_prompt_features(_generation("Fix the bug in this file"))
    activity = extract_activity_features(
        [
            _event("pre_tool_use", file_path="a.py"),
            _event("post_tool_use", file_path="a.py"),
            _event("after_file_edit", file_path="a.py"),
        ]
    )

    result = classify(prompt, activity)

    assert result.primary_language == "python"
    assert activity.languages["python"] == 1
