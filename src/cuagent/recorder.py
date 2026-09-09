from __future__ import annotations

import re
from datetime import datetime, timezone

from cuagent.models import (
    AgentAction,
    BusinessOutcomeRule,
    CapabilityArtifact,
    CapabilityStep,
    InputSpec,
    Observation,
    ObservedControl,
    OutputSpec,
    RecoverableConditionRule,
    HardFailureRule,
    RiskClass,
    StateCondition,
    ValueSource,
)
from cuagent.surface.playwright_surface import PlaywrightSurface


class ArtifactRecorder:
    def __init__(
        self,
        surface: PlaywrightSurface,
        capability_id: str,
        name: str,
        description: str,
        target_app: str,
        entry_point: str,
        allowed_hosts: list[str],
        params: dict[str, str],
        business_outcomes: list[BusinessOutcomeRule],
        recoverable_conditions: list[RecoverableConditionRule],
        hard_failures: list[HardFailureRule],
    ):
        self.surface = surface
        self.capability_id = capability_id
        self.name = name
        self.description = description
        self.target_app = target_app
        self.entry_point = entry_point
        self.allowed_hosts = allowed_hosts
        self.params = params
        self.business_outcomes = business_outcomes
        self.recoverable_conditions = recoverable_conditions
        self.hard_failures = hard_failures
        self.steps: list[CapabilityStep] = []
        self.outputs: dict[str, OutputSpec] = {}

    def record(
        self,
        action: AgentAction,
        control: ObservedControl | None,
        risk: RiskClass,
    ) -> CapabilityStep:
        target = self.surface.locator_candidates_for(control) if control else None
        step_id = f"step_{len(self.steps) + 1:02d}"
        if action.kind == "type":
            if action.value_from:
                value = ValueSource(parameter=action.value_from)
            else:
                value = ValueSource(literal=action.value or "")
            step = CapabilityStep(id=step_id, kind="type", target=target, value=value, risk=risk)
        elif action.kind == "click":
            step = CapabilityStep(id=step_id, kind="click", target=target, risk=risk)
        elif action.kind == "extract":
            output_name = action.output_name or f"output_{len(self.outputs) + 1}"
            step = CapabilityStep(id=step_id, kind="extract", target=target, output_name=output_name, risk=risk)
            self.outputs[output_name] = OutputSpec(
                name=output_name,
                type="string",
                description=f"Value extracted from {target.description if target else 'the final UI'}",
            )
        elif action.kind == "wait":
            step = CapabilityStep(id=step_id, kind="wait", wait_ms=action.wait_ms or 500)
        else:
            raise ValueError(action.kind)
        self.steps.append(step)
        return step

    def build(self, success_marker: str) -> CapabilityArtifact:
        inputs = [
            InputSpec(
                name=name,
                type="string",
                description=f"Invocation parameter: {name.replace('_', ' ')}",
                sensitive=False,
            )
            for name in self.params
        ]
        return CapabilityArtifact(
            capability_id=self.capability_id,
            capability_version=1,
            name=self.name,
            description=self.description,
            target_app=self.target_app,
            entry_point=self.entry_point,
            allowed_hosts=self.allowed_hosts,
            inputs=inputs,
            outputs=list(self.outputs.values()),
            steps=self.steps,
            success_checkpoint=StateCondition(kind="text_contains", value=success_marker),
            business_outcomes=self.business_outcomes,
            recoverable_conditions=self.recoverable_conditions,
            hard_failures=self.hard_failures,
            metadata={
                "created_at": datetime.now(timezone.utc).isoformat(),
                "created_by": "llm_discovery_recorder",
                "raw_model_transcript_persisted": False,
                "locator_order": ["label", "role_name", "css", "text", "coordinates"],
            },
        )


def slugify(text: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", text).strip("_").lower()
    return text[:60] or "capability"
