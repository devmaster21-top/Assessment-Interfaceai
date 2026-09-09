from __future__ import annotations

from cuagent.models import (
    BusinessOutcomeRule,
    HardFailureRule,
    RecoverableConditionRule,
    StateCondition,
)


def demo_business_outcomes() -> list[BusinessOutcomeRule]:
    return [
        BusinessOutcomeRule(
            code="member_not_found",
            description="The requested member does not exist.",
            condition=StateCondition(kind="text_contains", value="No member found"),
        )
    ]


def demo_recoverable_conditions() -> list[RecoverableConditionRule]:
    return [
        RecoverableConditionRule(
            code="session_expired",
            description="The application session expired; a human may re-authenticate in the same session.",
            condition=StateCondition(kind="text_contains", value="Session expired"),
            recovery="human_handoff",
            max_retries=1,
        )
    ]


def demo_hard_failures() -> list[HardFailureRule]:
    return [
        HardFailureRule(
            code="permission_denied",
            description="The current operator is not authorized to view the requested record.",
            condition=StateCondition(kind="text_contains", value="Permission denied"),
        )
    ]
