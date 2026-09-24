import pytest
from agent.safety_guard import SafetyGuard, SecurityScanResult


def test_scan_secrets_detection():
    text_with_key = "My API key is sk-ant-api03-abcdef1234567890abcdef1234567890 and gh token is ghp_1234567890abcdef1234567890abcdef1234"
    is_safe, detected, sanitized = SafetyGuard.scan_secrets(text_with_key)

    assert not is_safe
    assert len(detected) == 2
    assert "sk-ant-" not in sanitized
    assert "ghp_" not in sanitized
    assert "[REDACTED_SECRET]" in sanitized


def test_command_safety_blocking():
    # Dangerous commands
    res_wipe = SafetyGuard.check_command_safety("rm -rf /")
    assert not res_wipe.is_safe
    assert res_wipe.risk_level == "blocked"
    assert len(res_wipe.blocked_reasons) > 0

    res_forkbomb = SafetyGuard.check_command_safety(":(){ :|:& };:")
    assert not res_forkbomb.is_safe
    assert res_forkbomb.risk_level == "blocked"

    # Safe command
    res_safe = SafetyGuard.check_command_safety("pytest tests/ -v")
    assert res_safe.is_safe
    assert res_safe.risk_level == "clean"


def test_sanitize_for_persistence():
    payload = {
        "user": "developer",
        "nested": {
            "token": "ghp_1234567890abcdef1234567890abcdef1234",
            "items": ["safe_string", "sk-abcdef1234567890abcdef1234567890"],
        },
    }

    sanitized = SafetyGuard.sanitize_for_persistence(payload)
    assert "ghp_" not in sanitized["nested"]["token"]
    assert sanitized["nested"]["token"] == "[REDACTED_SECRET]"
    assert sanitized["nested"]["items"][0] == "safe_string"
    assert sanitized["nested"]["items"][1] == "[REDACTED_SECRET]"
