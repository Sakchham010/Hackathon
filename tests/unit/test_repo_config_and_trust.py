from pathlib import Path

from cursor_model_router.common.config import TrustedRepositoryConfig
from cursor_model_router.verification.repo_config import load_repo_config
from cursor_model_router.verification.trust import find_trust_entry


def test_load_repo_config_returns_none_when_file_missing(tmp_path: Path):
    assert load_repo_config(tmp_path, ".cursor-model-router.yaml") is None


def test_load_repo_config_parses_checks(tmp_path: Path):
    (tmp_path / ".cursor-model-router.yaml").write_text(
        """
        version: 1
        checks:
          - name: build
            command: "dotnet build"
            check_type: build
            timeout_seconds: 300
        """,
        encoding="utf-8",
    )

    result = load_repo_config(tmp_path, ".cursor-model-router.yaml")
    assert result is not None
    parsed, config_hash = result
    assert parsed.checks[0].name == "build"
    assert parsed.checks[0].command == "dotnet build"
    assert parsed.checks[0].check_type == "build"
    assert len(config_hash) == 64


def test_load_repo_config_returns_none_on_invalid_yaml(tmp_path: Path):
    (tmp_path / ".cursor-model-router.yaml").write_text("checks: [this is not valid: yaml:", encoding="utf-8")
    assert load_repo_config(tmp_path, ".cursor-model-router.yaml") is None


def test_find_trust_entry_matches_glob():
    entries = [TrustedRepositoryConfig(path_glob="c:/work/appian-monorepo/*")]
    match = find_trust_entry("c:/work/appian-monorepo/EnterpriseServices", entries)
    assert match is not None


def test_find_trust_entry_returns_none_when_unmatched():
    entries = [TrustedRepositoryConfig(path_glob="c:/work/appian-monorepo/*")]
    assert find_trust_entry("c:/other/repo", entries) is None
