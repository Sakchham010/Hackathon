from io import StringIO

from cursor_model_router.collector.hook import read_hook_payload


def test_read_hook_payload_parses_plain_json():
    payload = read_hook_payload(StringIO('{"hook_event_name":"sessionStart"}'))

    assert payload == {"hook_event_name": "sessionStart"}


def test_read_hook_payload_strips_windows_utf8_bom():
    payload = read_hook_payload(
        StringIO('\ufeff{"hook_event_name":"beforeSubmitPrompt","conversation_id":"conv-1"}')
    )

    assert payload["conversation_id"] == "conv-1"


def test_read_hook_payload_strips_powershell_mojibake_bom():
    payload = read_hook_payload(
        StringIO('\xef\xbb\xbf{"hook_event_name":"preToolUse","conversation_id":"conv-2"}')
    )

    assert payload["conversation_id"] == "conv-2"


def test_read_hook_payload_fails_open_for_invalid_json():
    assert read_hook_payload(StringIO("{invalid")) == {}
