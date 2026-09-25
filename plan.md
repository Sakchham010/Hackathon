---
name: Router Goals One Three
overview: Build a standalone Python `cursor-model-router` MVP that passively observes normal Cursor work, asynchronously classifies each task, and stores analysis-ready outcome signals in MongoDB. Install fail-open user-level hooks so it can observe `appian-monorepo` and other repositories without rerunning tasks across models.
todos:
  - id: shared-foundation
    content: Scaffold the standalone Python package, configuration, MongoDB collections/indexes, and analysis-ready records.
    status: completed
  - id: goal-1-telemetry
    content: Implement and validate fail-open user-level Cursor telemetry hooks and local ingestion.
    status: completed
  - id: goal-2-classification
    content: Implement asynchronous, versioned task classification from prompts, repository metadata, and observed activity.
    status: completed
  - id: goal-3-outcomes
    content: Capture non-authoritative outcome signals and trusted user-defined post-session build/test results.
    status: completed
isProject: false
---

# Plan for Cursor Router Goals 1–3

## Scope and constraint

- Create a standalone Python 3.10+ project; repositories such as `appian-monorepo` are observed data sources rather than hosting the router.
- Use MongoDB through a configurable URI, with a local container for development and compatibility with MongoDB Atlas for shared deployments.
- Install user hooks in `~/.cursor/hooks.json`, preserving unrelated hooks and defaulting to fail-open behavior.
- Do not run a task repeatedly with different models and do not launch Cursor agents through the SDK.
- Without a Cursor Team Admin API key, IDE hooks do not expose exact tokens or billed cost. Keep those fields null with an explicit `unavailable` source; do not estimate prices.
- Treat the dataset as observational: it can identify model/outcome associations for similar task classes, but model choice is subject to selection bias. Future analysis must report sample size and uncertainty rather than claim causal superiority.
- Defer recommendations, routing, machine learning, and a definitive success label until the passive data and outcome signals are trustworthy.

## 1. Establish the shared project and data contract

- Scaffold [`pyproject.toml`](pyproject.toml), [`src/cursor_model_router/cli.py`](src/cursor_model_router/cli.py), configuration loading, a local [`compose.yaml`](compose.yaml), and MongoDB access under [`src/cursor_model_router/database/`](src/cursor_model_router/database/).
- Create separate `tasks`, `task_events`, `task_classifications`, `verification_definitions`, `verification_runs`, and `outcome_signals` collections. Keep high-volume events out of task documents to avoid unbounded arrays, join them with stable task/conversation IDs, and denormalize only the model/repository/category fields needed for analysis.
- Use PyMongo's asynchronous client in the collector/worker services and a small repository layer so persistence behavior is testable without leaking MongoDB calls throughout the application.
- Define validated, versioned document models containing conversation/generation IDs, exact model ID and parameters, repository/commit and working-tree fingerprint, lifecycle timestamps/status, tool correlation IDs, classifier version/confidence, and provenance for every outcome signal.
- Create unique indexes for event idempotency and classifier/result versions, plus compound indexes for conversation lookup, pending classification work, repository/time queries, and later model-by-task-category analysis. Apply collection validators and indexes through an idempotent `router db initialize` command.
- Use atomic upserts, UTC BSON datetimes, and repository/path normalization so concurrent hooks cannot corrupt or duplicate records. Keep schema-versioned migration scripts for future document transformations instead of relational migrations.
- Add config for database/spool locations, repository allow/deny rules, ignored paths, retention, and secret redaction. Never persist file contents or complete tool output by default.

## 2. Goal 1 — Observe real Cursor Agent runs

- Implement a thin stdin/stdout hook entry point in [`src/cursor_model_router/collector/hook.py`](src/cursor_model_router/collector/hook.py) and normalization/redaction in [`src/cursor_model_router/collector/events.py`](src/cursor_model_router/collector/events.py).
- Subscribe to `sessionStart`, `beforeSubmitPrompt`, `preToolUse`, `postToolUse`, `postToolUseFailure`, `afterFileEdit`, `stop`, and `sessionEnd`. Correlate records by `conversation_id`, `generation_id`, and `tool_use_id`; capture model/model parameters, workspace root, redacted prompt, file paths, shell commands, tool calls, errors, durations, and terminal state.
- Send events to a local collector in [`src/cursor_model_router/collector/service.py`](src/cursor_model_router/collector/service.py); when it is unavailable, atomically spool JSON events and drain them later so telemetry never blocks Cursor work.
- Add [`src/cursor_model_router/collector/install.py`](src/cursor_model_router/collector/install.py) to merge generated commands into the user hook configuration, quote Windows paths safely, create a backup, support uninstall, and preserve all existing hooks.
- Verify with fixture payloads plus an end-to-end Cursor session that one task record contains the prompt, exact model, repository, files read/edited, commands/tools, failures, elapsed time, and completion status.

## 3. Goal 2 — Classify each observed task

- Enqueue classification after `stop`/`sessionEnd`; keep the hook process fast and perform all feature extraction asynchronously in [`src/cursor_model_router/classification/worker.py`](src/cursor_model_router/classification/worker.py).
- Extract stable static features in [`src/cursor_model_router/classification/features.py`](src/cursor_model_router/classification/features.py): repository languages/frameworks, prompt shape, requested and touched files, edit scope, tool/command patterns, error or stack-trace presence, and build/test activity.
- Implement a versioned rules classifier in [`src/cursor_model_router/classification/rules.py`](src/cursor_model_router/classification/rules.py) for task category, subcategory/domain, primary language, debugging/feature/refactor intent, cross-file scope, and coarse complexity. Store confidence, matched evidence, taxonomy version, and classifier version.
- Define a provider interface in [`src/cursor_model_router/classification/providers.py`](src/cursor_model_router/classification/providers.py) for optional asynchronous LLM classification when rules are low-confidence. Keep it disabled by default, store the provider/model/prompt version when enabled, and retain the rules result for comparison.
- Make classifications append-only and re-runnable so improved taxonomies can classify historical tasks without overwriting prior results. Expose `router classify pending` and `router classify replay --version <version>`.

## 4. Goal 3 — Capture outcome and user-defined verification signals

- Record weak signals—Agent completion/error/abort, failed tools, shell exit evidence, build/test commands observed during the conversation, follow-up generations, and elapsed time—without collapsing them into `success = true/false`.
- Support a trusted per-repository config such as `.cursor-model-router.yaml` that names post-session build/test/lint commands, timeouts, and working directories. Require explicit trust in the router’s central config before executing commands from any repository.
- On `sessionEnd`, enqueue configured checks in [`src/cursor_model_router/verification/worker.py`](src/cursor_model_router/verification/worker.py) rather than running them in the fire-and-forget hook. Capture command name, exit code, duration, timestamps, commit/working-tree fingerprint, and bounded/redacted output.
- Add an ingestion contract and `router outcome record --task-id <id>` command so users, existing hooks, or CI jobs can submit build/test results after the conversation ends. Retain source/provenance and keep repeated submissions as separate evidence records.
- Keep verification results as individual evidence records. A later analysis policy may derive outcome scores, but the MVP must distinguish observed signals, user-supplied results, and router-executed checks.

## 5. Verification and documentation

- Unit-test hook normalization/redaction, hook-config merging, document validation, repository upserts, feature extraction, classifier versioning/confidence, trust enforcement, and outcome ingestion.
- Integration-test against a disposable MongoDB container: concurrent hook ingestion, unique-index idempotency, spool recovery after database downtime, asynchronous classification, post-session command timeouts, and repeated external result submissions.
- Run a manual Cursor smoke session in `appian-monorepo` and confirm telemetry, classification, and configured post-session checks join to one conversation without changing repository files.
- Add `router export --format parquet|jsonl` and documented analysis views for task class, exact model, observation count, completion/error signals, and verification pass rates. Do not emit a “best model” recommendation in the MVP.
- Document installation, hook privacy/retention controls, repository trust and check configuration, custom result submission, classifier taxonomy/versioning, observational-data limitations, unavailable cost fields, and clean uninstall in [`README.md`](README.md).
