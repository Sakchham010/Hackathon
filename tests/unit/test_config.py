from pathlib import Path

from cursor_model_router.common.config import load_config


def test_load_config_defaults_when_no_file(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("CURSOR_MODEL_ROUTER_CONFIG", raising=False)
    monkeypatch.setenv("CURSOR_MODEL_ROUTER_HOME", str(tmp_path / "does-not-exist"))
    monkeypatch.delenv("CURSOR_MODEL_ROUTER_MONGO_URI", raising=False)
    monkeypatch.delenv("CURSOR_MODEL_ROUTER_DATABASE", raising=False)

    config = load_config()

    assert config.database_name == "cursor_model_router"
    assert config.mongo_uri.startswith("mongodb://")
    assert config.redaction.max_prompt_chars > 0


def test_load_config_reads_yaml_file(tmp_path: Path):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
        database_name: my_custom_db
        redaction:
          max_prompt_chars: 123
        repositories:
          deny:
            - "c:/blocked/*"
        """,
        encoding="utf-8",
    )

    config = load_config(config_path)

    assert config.database_name == "my_custom_db"
    assert config.redaction.max_prompt_chars == 123
    assert config.repositories.deny == ["c:/blocked/*"]


def test_env_vars_override_file(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text("database_name: from_file\n", encoding="utf-8")
    monkeypatch.setenv("CURSOR_MODEL_ROUTER_DATABASE", "from_env")

    config = load_config(config_path)

    assert config.database_name == "from_env"
