from __future__ import annotations

from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ActionKind(str, Enum):
    CLICK = "click"
    TYPE = "type"
    EXTRACT = "extract"
    WAIT = "wait"


class RiskClass(str, Enum):
    SAFE = "safe"
    RISKY = "risky"


class LocatorCandidate(BaseModel):
    strategy: Literal["label", "role_name", "text", "css", "coordinates"]
    value: str | None = None
    role: str | None = None
    x: float | None = None
    y: float | None = None

    @model_validator(mode="after")
    def validate_locator(self) -> "LocatorCandidate":
        if self.strategy == "coordinates":
            if self.x is None or self.y is None:
                raise ValueError("coordinate locator requires x and y")
        elif not self.value:
            raise ValueError(f"{self.strategy} locator requires value")
        if self.strategy == "role_name" and not self.role:
            raise ValueError("role_name locator requires role")
        return self


class TargetLocator(BaseModel):
    description: str
    candidates: list[LocatorCandidate] = Field(min_length=1)


class ValueSource(BaseModel):
    literal: str | None = None
    parameter: str | None = None

    @model_validator(mode="after")
    def exactly_one_source(self) -> "ValueSource":
        if (self.literal is None) == (self.parameter is None):
            raise ValueError("exactly one of literal or parameter is required")
        return self


class CapabilityStep(BaseModel):
    id: str
    kind: ActionKind
    target: TargetLocator | None = None
    value: ValueSource | None = None
    output_name: str | None = None
    risk: RiskClass = RiskClass.SAFE
    wait_ms: int | None = None
    note: str | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "CapabilityStep":
        if self.kind in {ActionKind.CLICK, ActionKind.TYPE, ActionKind.EXTRACT} and not self.target:
            raise ValueError(f"{self.kind} requires target")
        if self.kind == ActionKind.TYPE and not self.value:
            raise ValueError("type requires value")
        if self.kind == ActionKind.EXTRACT and not self.output_name:
            raise ValueError("extract requires output_name")
        if self.kind == ActionKind.WAIT and not self.wait_ms:
            raise ValueError("wait requires wait_ms")
        return self


class InputSpec(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str
    required: bool = True
    sensitive: bool = False


class OutputSpec(BaseModel):
    name: str
    type: Literal["string", "integer", "number", "boolean"] = "string"
    description: str


class StateCondition(BaseModel):
    kind: Literal["text_contains", "url_contains", "title_contains"]
    value: str


class BusinessOutcomeRule(BaseModel):
    code: str
    description: str
    condition: StateCondition




class RecoverableConditionRule(BaseModel):
    code: str
    description: str
    condition: StateCondition
    recovery: Literal["wait_retry", "human_handoff"] = "wait_retry"
    max_retries: int = 1


class HardFailureRule(BaseModel):
    code: str
    description: str
    condition: StateCondition


class CapabilityArtifact(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    capability_id: str
    capability_version: int = 1
    name: str
    description: str
    target_app: str
    entry_point: str
    allowed_hosts: list[str]
    inputs: list[InputSpec]
    outputs: list[OutputSpec]
    steps: list[CapabilityStep]
    success_checkpoint: StateCondition
    business_outcomes: list[BusinessOutcomeRule] = []
    recoverable_conditions: list[RecoverableConditionRule] = []
    hard_failures: list[HardFailureRule] = []
    metadata: dict[str, Any] = {}


class RunStatus(str, Enum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    FAILURE = "failure"
    ESCALATED = "escalated"


class RunError(BaseModel):
    code: str
    message: str
    step_id: str | None = None
    expected: str | None = None
    observed: str | None = None
    recoverable: bool = False


class RunResult(BaseModel):
    status: RunStatus
    outputs: dict[str, Any] = {}
    business_outcome: str | None = None
    error: RunError | None = None
    run_id: str
    evidence_path: str | None = None


class ObservedControl(BaseModel):
    index: int
    tag: str
    role: str | None = None
    accessible_name: str | None = None
    text: str | None = None
    label: str | None = None
    name_attr: str | None = None
    input_type: str | None = None
    placeholder: str | None = None
    aria_label: str | None = None
    href: str | None = None
    bbox: dict[str, float] | None = None


class Observation(BaseModel):
    url: str
    title: str
    visible_text: str
    controls: list[ObservedControl]
    screenshot_path: str | None = None


class AgentAction(BaseModel):
    kind: Literal["click", "type", "extract", "wait"]
    target_index: int | None = None
    value: str | None = None
    value_from: str | None = None
    output_name: str | None = None
    wait_ms: int | None = None


class AgentDecision(BaseModel):
    status: Literal["continue", "success", "blocked"]
    reason: str
    action: AgentAction | None = None
    success_marker: str | None = None


class InterventionRequest(BaseModel):
    intervention_id: str
    run_id: str
    reason: str
    current_step: str | None = None
    screenshot_path: str | None = None
    state_summary: str
    control_owner: Literal["automation", "human"] = "human"
