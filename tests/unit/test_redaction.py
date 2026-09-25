from cursor_model_router.common.redaction import redact_secrets, sanitize_free_text, truncate


def test_redact_secrets_masks_api_key_assignment():
    text = "export API_KEY=abcdef1234567890 and continue"
    redacted = redact_secrets(text)
    assert "abcdef1234567890" not in redacted
    assert "[REDACTED]" in redacted


def test_redact_secrets_masks_known_token_prefixes():
    text = "token is ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd here"
    redacted = redact_secrets(text)
    assert "ghp_ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789abcd" not in redacted


def test_truncate_keeps_short_text_unchanged():
    assert truncate("hello", 10) == "hello"


def test_truncate_adds_suffix_when_over_limit():
    result = truncate("a" * 100, 20)
    assert len(result) <= 20
    assert result.endswith("…[truncated]")


def test_sanitize_free_text_handles_none():
    assert sanitize_free_text(None, 10) is None


def test_sanitize_free_text_redacts_then_truncates():
    text = "password: supersecretvalue " + ("x" * 50)
    result = sanitize_free_text(text, 30)
    assert "supersecretvalue" not in result
    assert len(result) <= 30
