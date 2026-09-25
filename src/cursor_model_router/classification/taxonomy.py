"""Static vocabulary used by the rules classifier.

Matched with word/phrase-boundary rules in
:mod:`cursor_model_router.classification.rules`, not raw substrings, so e.g.
``"add"`` never matches inside ``"address"``.
"""

from __future__ import annotations

EXTENSION_LANGUAGE_MAP: dict[str, str] = {
    ".cs": "csharp",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".py": "python",
    ".java": "java",
    ".go": "go",
    ".rb": "ruby",
    ".rs": "rust",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".c": "c",
    ".h": "cpp",
    ".sql": "sql",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".json": "json",
    ".ps1": "powershell",
    ".sh": "shell",
}

CATEGORY_DEBUGGING_KEYWORDS = (
    "bug",
    "fix",
    "error",
    "exception",
    "crash",
    "broken",
    "failing",
    "traceback",
    "stack trace",
    "not working",
    "regression",
)

CATEGORY_FEATURE_KEYWORDS = (
    "add",
    "implement",
    "create",
    "new feature",
    "support for",
    "build a",
)

CATEGORY_REFACTOR_KEYWORDS = (
    "refactor",
    "clean up",
    "extract",
    "rename",
    "simplify",
    "reorganize",
    "restructure",
)

CATEGORY_SIMPLE_EDIT_KEYWORDS = (
    "typo",
    "update comment",
    "rename variable",
    "change constant",
    "update text",
    "update label",
)

DOMAIN_KEYWORDS: dict[str, tuple[str, ...]] = {
    "concurrency": ("deadlock", "race condition", "thread", "async", "lock", "mutex"),
    "database": ("sql", "query", "migration", "database", "index", "entity framework", "dbcontext"),
    "networking": ("http", "api", "endpoint", "rest", "grpc", "socket", "timeout"),
    "ui": ("component", "css", "style", "layout", "button", "render", "ui"),
    "performance": ("slow", "performance", "n+1", "memory", "allocation", "latency"),
    "security": ("auth", "token", "credential", "vulnerability", "secret", "permission"),
}

BUILD_COMMAND_KEYWORDS = ("build", "compile", "msbuild", "dotnet build", "npm run build", "tsc")
TEST_COMMAND_KEYWORDS = ("test", "pytest", "dotnet test", "npm test", "jest", "vitest", "mocha")
STACK_TRACE_KEYWORDS = ("traceback", "exception", "at line", "stack trace", "error cs", "unhandled")
