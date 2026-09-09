from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlparse

from .models import ActionKind, ObservedControl, RiskClass


class PolicyViolation(RuntimeError):
    pass


@dataclass(frozen=True)
class PolicyConfig:
    allowed_hosts: set[str]
    allowed_actions: set[ActionKind]
    risky_terms: tuple[str, ...] = (
        "delete",
        "remove",
        "close account",
        "suspend",
        "transfer",
        "submit payment",
        "wire",
    )


class SafetyPolicy:
    def __init__(self, config: PolicyConfig):
        self.config = config

    def assert_url_allowed(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if host not in self.config.allowed_hosts:
            raise PolicyViolation(f"host '{host}' is outside the allowlist")

    def assert_action_allowed(self, action: ActionKind) -> None:
        if action not in self.config.allowed_actions:
            raise PolicyViolation(f"action '{action.value}' is not allowed")

    def classify_control(self, control: ObservedControl | None) -> RiskClass:
        if not control:
            return RiskClass.SAFE
        descriptor = " ".join(
            part or ""
            for part in [
                control.accessible_name,
                control.text,
                control.label,
                control.name_attr,
            ]
        ).lower()
        if any(term in descriptor for term in self.config.risky_terms):
            return RiskClass.RISKY
        return RiskClass.SAFE

    def assert_safe_input(self, control: ObservedControl | None) -> None:
        if control and (control.input_type or "").lower() == "password":
            raise PolicyViolation("typing into password fields is blocked")
