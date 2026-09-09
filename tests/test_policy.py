import pytest

from cuagent.models import ActionKind, ObservedControl
from cuagent.policy import PolicyConfig, PolicyViolation, SafetyPolicy


def make_policy():
    return SafetyPolicy(
        PolicyConfig(
            allowed_hosts={"127.0.0.1"},
            allowed_actions={ActionKind.CLICK, ActionKind.TYPE, ActionKind.EXTRACT, ActionKind.WAIT},
        )
    )


def test_host_allowlist():
    p = make_policy()
    p.assert_url_allowed("http://127.0.0.1:8000/")
    with pytest.raises(PolicyViolation):
        p.assert_url_allowed("https://example.com/")


def test_risky_control_classification():
    p = make_policy()
    c = ObservedControl(index=1, tag="button", role="button", accessible_name="Suspend Account")
    assert p.classify_control(c).value == "risky"


def test_password_typing_blocked():
    p = make_policy()
    c = ObservedControl(index=0, tag="input", input_type="password")
    with pytest.raises(PolicyViolation):
        p.assert_safe_input(c)
