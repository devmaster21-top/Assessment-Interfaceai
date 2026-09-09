from pathlib import Path

import pytest

from cuagent.models import (
    BusinessOutcomeRule,
    CapabilityArtifact,
    CapabilityStep,
    InputSpec,
    LocatorCandidate,
    OutputSpec,
    StateCondition,
    TargetLocator,
    ValueSource,
)
from cuagent.policy import PolicyConfig, SafetyPolicy
from cuagent.models import ActionKind
from cuagent.replay import ReplayRunner


def target(name: str) -> TargetLocator:
    return TargetLocator(description=name, candidates=[LocatorCandidate(strategy="text", value=name)])


def artifact() -> CapabilityArtifact:
    return CapabilityArtifact(
        capability_id="lookup_member_savings",
        name="Lookup member savings",
        description="Look up a member and read savings balance",
        target_app="fake",
        entry_point="http://127.0.0.1:8000/",
        allowed_hosts=["127.0.0.1"],
        inputs=[InputSpec(name="member_id", description="Member ID")],
        outputs=[OutputSpec(name="savings_balance", description="Savings balance")],
        steps=[
            CapabilityStep(id="step_01", kind="click", target=target("Member Servicing")),
            CapabilityStep(
                id="step_02",
                kind="type",
                target=target("Member ID"),
                value=ValueSource(parameter="member_id"),
            ),
            CapabilityStep(id="step_03", kind="click", target=target("Search Member")),
            CapabilityStep(id="step_04", kind="click", target=target("Open Savings Account")),
            CapabilityStep(
                id="step_05",
                kind="extract",
                target=target("Savings Balance Value"),
                output_name="savings_balance",
            ),
        ],
        success_checkpoint=StateCondition(kind="text_contains", value="Savings Account"),
        business_outcomes=[
            BusinessOutcomeRule(
                code="member_not_found",
                description="No such member",
                condition=StateCondition(kind="text_contains", value="No member found"),
            )
        ],
    )


class FakeSurface:
    def __init__(self):
        self.state = "home"
        self.member_id = None

    async def start(self, entry_point: str):
        self.state = "home"

    async def observe(self, screenshot_path=None):
        from cuagent.models import Observation

        text = {
            "home": "Operations Menu Member Servicing",
            "search": "Member Search Member ID Search Member",
            "not_found": "No member found",
            "detail": "Member Detail Open Savings Account",
            "savings": "Savings Account Savings Balance $925.04",
        }[self.state]
        return Observation(url="http://127.0.0.1:8000/", title=self.state, visible_text=text, controls=[])

    async def click_locator(self, locator):
        if locator.description == "Member Servicing":
            self.state = "search"
        elif locator.description == "Search Member":
            self.state = "not_found" if self.member_id == "99999" else "detail"
        elif locator.description == "Open Savings Account":
            self.state = "savings"
        return "text"

    async def type_locator(self, locator, value):
        self.member_id = value
        return "text"

    async def extract_locator(self, locator):
        return "$925.04", "text"

    async def wait(self, ms: int):
        return None

    async def close(self):
        return None


@pytest.mark.asyncio
async def test_replay_success_without_llm(tmp_path: Path):
    p = SafetyPolicy(
        PolicyConfig(
            allowed_hosts={"127.0.0.1"},
            allowed_actions={ActionKind.CLICK, ActionKind.TYPE, ActionKind.EXTRACT, ActionKind.WAIT},
        )
    )
    runner = ReplayRunner(FakeSurface(), p, tmp_path, human_interactive=False)
    result = await runner.run(artifact(), {"member_id": "67890"})
    assert result.status.value == "success"
    assert result.outputs["savings_balance"] == "$925.04"


@pytest.mark.asyncio
async def test_replay_returns_business_outcome_not_crash(tmp_path: Path):
    p = SafetyPolicy(
        PolicyConfig(
            allowed_hosts={"127.0.0.1"},
            allowed_actions={ActionKind.CLICK, ActionKind.TYPE, ActionKind.EXTRACT, ActionKind.WAIT},
        )
    )
    runner = ReplayRunner(FakeSurface(), p, tmp_path, human_interactive=False)
    result = await runner.run(artifact(), {"member_id": "99999"})
    assert result.status.value == "business_outcome"
    assert result.business_outcome == "member_not_found"
