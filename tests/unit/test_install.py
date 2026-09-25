import json
from pathlib import Path

from cursor_model_router.collector.install import (
    SUBSCRIBED_EVENTS,
    install_user_hooks,
    resolve_router_command,
    uninstall_user_hooks,
)


def test_install_creates_hooks_file_when_missing(tmp_path: Path):
    path = install_user_hooks(home_override=tmp_path)

    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["version"] == 1
    for event_name in SUBSCRIBED_EVENTS:
        assert len(document["hooks"][event_name]) == 1


def test_install_preserves_unrelated_existing_hooks(tmp_path: Path):
    hooks_dir = tmp_path / ".cursor"
    hooks_dir.mkdir(parents=True)
    existing = {
        "version": 1,
        "hooks": {
            "beforeShellExecution": [{"command": "./hooks/some-other-tool.sh"}],
            "sessionStart": [{"command": "./hooks/unrelated.sh"}],
        },
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(existing), encoding="utf-8")

    path = install_user_hooks(home_override=tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert {"command": "./hooks/some-other-tool.sh"} in document["hooks"]["beforeShellExecution"]
    assert {"command": "./hooks/unrelated.sh"} in document["hooks"]["sessionStart"]
    assert len(document["hooks"]["sessionStart"]) == 2


def test_install_is_idempotent(tmp_path: Path):
    install_user_hooks(home_override=tmp_path)
    path = install_user_hooks(home_override=tmp_path)

    document = json.loads(path.read_text(encoding="utf-8"))
    for event_name in SUBSCRIBED_EVENTS:
        assert len(document["hooks"][event_name]) == 1


def test_install_upgrades_legacy_marker_command(tmp_path: Path):
    hooks_dir = tmp_path / ".cursor"
    hooks_dir.mkdir(parents=True)
    legacy_command = '"C:\\old\\router.exe" hook # cursor-model-router'
    existing = {
        "version": 1,
        "hooks": {
            event_name: [{"command": legacy_command, "failClosed": False}]
            for event_name in SUBSCRIBED_EVENTS
        },
    }
    (hooks_dir / "hooks.json").write_text(json.dumps(existing), encoding="utf-8")

    path = install_user_hooks(home_override=tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))

    for event_name in SUBSCRIBED_EVENTS:
        assert document["hooks"][event_name] == [
            {"command": resolve_router_command(), "failClosed": False}
        ]


def test_uninstall_removes_only_router_entries(tmp_path: Path):
    install_user_hooks(home_override=tmp_path)
    hooks_path = tmp_path / ".cursor" / "hooks.json"
    document = json.loads(hooks_path.read_text(encoding="utf-8"))
    document["hooks"]["sessionStart"].append({"command": "./hooks/unrelated.sh"})
    hooks_path.write_text(json.dumps(document), encoding="utf-8")

    path = uninstall_user_hooks(home_override=tmp_path)
    document = json.loads(path.read_text(encoding="utf-8"))

    assert document["hooks"]["sessionStart"] == [{"command": "./hooks/unrelated.sh"}]
    assert "beforeSubmitPrompt" not in document["hooks"]


def test_resolve_router_command_returns_non_empty_string():
    command = resolve_router_command()
    assert "hook" in command
    assert "#" not in command
