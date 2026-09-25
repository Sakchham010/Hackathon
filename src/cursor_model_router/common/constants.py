"""Shared constants for cursor-model-router.

All magic strings/numbers with semantic meaning live here so they are named,
grouped, and reused instead of scattered across the codebase.
"""

from __future__ import annotations


class ConfigDefaults:
    CONFIG_DIR_NAME = ".cursor-model-router"
    CONFIG_FILE_NAME = "config.yaml"
    DEFAULT_MONGO_URI = "mongodb://localhost:27117"
    DEFAULT_DATABASE_NAME = "cursor_model_router"
    DEFAULT_SPOOL_DIR_NAME = "spool"
    DEFAULT_LOG_DIR_NAME = "logs"
    SPOOL_DRAIN_BATCH_SIZE = 200
    SPOOL_FILE_SUFFIX = ".jsonl"
    SPOOL_FILE_TMP_SUFFIX = ".jsonl.tmp"
    DEFAULT_RETENTION_DAYS = 180
    DEFAULT_MAX_PROMPT_CHARS = 10000
    DEFAULT_MAX_TOOL_OUTPUT_CHARS = 2000
    DEFAULT_MAX_COMMAND_OUTPUT_CHARS = 4000
    MONGO_SERVER_SELECTION_TIMEOUT_MS = 1500
    MONGO_CONNECT_TIMEOUT_MS = 1500


class CollectionNames:
    TASKS = "tasks"
    TASK_GENERATIONS = "task_generations"
    TASK_EVENTS = "task_events"
    TASK_CLASSIFICATIONS = "task_classifications"
    VERIFICATION_DEFINITIONS = "verification_definitions"
    VERIFICATION_RUNS = "verification_runs"
    OUTCOME_SIGNALS = "outcome_signals"
    SCHEMA_META = "schema_meta"


# Fallback generation identity for hook events that arrive without a
# Cursor-supplied ``generation_id`` (e.g. legacy hooks). Using one explicit,
# named bucket per conversation keeps these events grouped together without
# ever silently attaching them to whichever real generation happens to be
# open at the time.
UNSCOPED_GENERATION_ID = "unscoped"


class TaskStatus:
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ABORTED = "aborted"
    ERROR = "error"


class HookEventType:
    SESSION_START = "session_start"
    BEFORE_SUBMIT_PROMPT = "before_submit_prompt"
    PRE_TOOL_USE = "pre_tool_use"
    POST_TOOL_USE = "post_tool_use"
    POST_TOOL_USE_FAILURE = "post_tool_use_failure"
    AFTER_FILE_EDIT = "after_file_edit"
    STOP = "stop"
    SESSION_END = "session_end"


class ClassificationSource:
    RULES = "rules"
    LLM = "llm"


class OutcomeSignalType:
    AGENT_STATUS = "agent_status"
    TOOL_FAILURE = "tool_failure"
    SHELL_EXIT = "shell_exit"
    BUILD_TEST_ACTIVITY = "build_test_activity"
    FOLLOW_UP_GENERATION = "follow_up_generation"


class OutcomeSource:
    OBSERVED = "observed"
    ROUTER_VERIFICATION = "router_verification"
    USER_SUBMITTED = "user_submitted"


class VerificationMethod:
    AUTOMATED = "automated"
    MANUAL = "manual"
    NOT_VERIFIABLE = "not_verifiable"


class VerificationCheckType:
    TEST = "test"
    BUILD = "build"
    LINT = "lint"
    BEHAVIOR = "behavior"
    RESEARCH = "research"
    OTHER = "other"


class VerificationRunStatus:
    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    PARTIALLY_PASSED = "partially_passed"
    FAILED = "failed"
    TIMED_OUT = "timed_out"
    ERROR = "error"
    INCONCLUSIVE = "inconclusive"
    SKIPPED = "skipped"

class RepoConfigFileName:
    DEFAULT = ".cursor-model-router.yaml"


class ExitCode:
    OK = 0
    GENERIC_ERROR = 1
    CONFIG_ERROR = 2
