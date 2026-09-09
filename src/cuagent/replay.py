from __future__ import annotations

import uuid
from pathlib import Path

from cuagent.evidence import EvidenceLogger
from cuagent.handoff import HumanHandoff
from cuagent.models import (
    ActionKind,
    CapabilityArtifact,
    CapabilityStep,
    RunError,
    RunResult,
    RunStatus,
    StateCondition,
)
from cuagent.policy import PolicyViolation, SafetyPolicy
from cuagent.surface.playwright_surface import PlaywrightSurface


class ReplayRunner:
    def __init__(
        self,
        surface: PlaywrightSurface,
        policy: SafetyPolicy,
        evidence_root: Path,
        human_interactive: bool = True,
    ):
        self.surface = surface
        self.policy = policy
        self.run_id = str(uuid.uuid4())[:8]
        self.logger = EvidenceLogger(evidence_root, self.run_id, "replay")
        self.handoff = HumanHandoff(self.logger, interactive=human_interactive)
        self._recoverable_seen: dict[str, int] = {}

    async def _condition_matches(self, condition: StateCondition) -> bool:
        obs = await self.surface.observe()
        if condition.kind == "text_contains":
            return condition.value.lower() in obs.visible_text.lower()
        if condition.kind == "url_contains":
            return condition.value.lower() in obs.url.lower()
        if condition.kind == "title_contains":
            return condition.value.lower() in obs.title.lower()
        return False

    async def _detect_business_outcome(self, artifact: CapabilityArtifact) -> str | None:
        for rule in artifact.business_outcomes:
            if await self._condition_matches(rule.condition):
                return rule.code
        return None

    async def _detect_hard_failure(self, artifact: CapabilityArtifact) -> tuple[str, str] | None:
        for rule in artifact.hard_failures:
            if await self._condition_matches(rule.condition):
                return rule.code, rule.description
        return None

    async def _handle_recoverable_condition(self, artifact: CapabilityArtifact, current_step: str | None) -> bool:
        """Returns True if replay should re-observe and continue, False if no rule matched."""
        for rule in artifact.recoverable_conditions:
            if not await self._condition_matches(rule.condition):
                continue
            seen = self._recoverable_seen.get(rule.code, 0)
            if seen >= rule.max_retries:
                return False
            self._recoverable_seen[rule.code] = seen + 1
            obs = await self.surface.observe(
                str(self.logger.screenshot_dir / f"recoverable-{rule.code}-{seen + 1}.png")
            )
            self.logger.emit(
                "recoverable_condition",
                code=rule.code,
                description=rule.description,
                recovery=rule.recovery,
                attempt=seen + 1,
                step_id=current_step,
            )
            if rule.recovery == "wait_retry":
                await self.surface.wait(750)
                return True
            await self.handoff.intervene(rule.description, obs, current_step=current_step)
            return self.handoff.interactive
        return False

    async def _execute_step(self, step: CapabilityStep, params: dict[str, str], outputs: dict[str, str]) -> str:
        if step.kind == ActionKind.CLICK:
            assert step.target
            return await self.surface.click_locator(step.target)
        if step.kind == ActionKind.TYPE:
            assert step.target and step.value
            value = params[step.value.parameter] if step.value.parameter else (step.value.literal or "")
            return await self.surface.type_locator(step.target, value)
        if step.kind == ActionKind.EXTRACT:
            assert step.target and step.output_name
            value, strategy = await self.surface.extract_locator(step.target)
            outputs[step.output_name] = value
            return strategy
        if step.kind == ActionKind.WAIT:
            await self.surface.wait(step.wait_ms or 500)
            return "timer"
        raise RuntimeError(f"unsupported step kind: {step.kind}")

    async def run(self, artifact: CapabilityArtifact, params: dict[str, str]) -> RunResult:
        outputs: dict[str, str] = {}
        try:
            required = {x.name for x in artifact.inputs if x.required}
            missing = sorted(required - params.keys())
            if missing:
                return RunResult(
                    status=RunStatus.FAILURE,
                    run_id=self.run_id,
                    error=RunError(code="missing_inputs", message=f"Missing required inputs: {missing}"),
                )

            await self.surface.start(artifact.entry_point)
            self.policy.assert_url_allowed(artifact.entry_point)
            self.logger.emit(
                "replay_started",
                capability_id=artifact.capability_id,
                version=artifact.capability_version,
            )

            for idx, step in enumerate(artifact.steps, start=1):
                shot = str(self.logger.screenshot_dir / f"before-{idx:02d}-{step.id}.png")
                obs = await self.surface.observe(shot)
                self.policy.assert_url_allowed(obs.url)

                outcome = await self._detect_business_outcome(artifact)
                if outcome:
                    self.logger.emit("business_outcome", step_id=step.id, code=outcome)
                    return RunResult(
                        status=RunStatus.BUSINESS_OUTCOME,
                        business_outcome=outcome,
                        outputs=outputs,
                        run_id=self.run_id,
                        evidence_path=str(self.logger.log_path),
                    )

                hard = await self._detect_hard_failure(artifact)
                if hard:
                    code, description = hard
                    self.logger.emit("hard_failure_condition", step_id=step.id, code=code)
                    return RunResult(
                        status=RunStatus.FAILURE,
                        outputs=outputs,
                        run_id=self.run_id,
                        evidence_path=str(self.logger.log_path),
                        error=RunError(
                            code=code,
                            message=description,
                            step_id=step.id,
                            recoverable=False,
                        ),
                    )

                if await self._handle_recoverable_condition(artifact, step.id):
                    # Same browser context stays alive while the human fixes the recoverable state.
                    obs = await self.surface.observe(
                        str(
                            self.logger.screenshot_dir
                            / f"after-recovery-{idx:02d}-{step.id}.png"
                        )
                    )
                    self.policy.assert_url_allowed(obs.url)

                    # Do not blindly continue if the human intervention did not actually
                    # clear the recoverable condition.
                    for rule in artifact.recoverable_conditions:
                        if await self._condition_matches(rule.condition):
                            self.logger.emit(
                                "recovery_failed",
                                step_id=step.id,
                                code=rule.code,
                                message="Recoverable condition remained after human intervention.",
                            )

                            return RunResult(
                                status=RunStatus.FAILURE,
                                outputs=outputs,
                                run_id=self.run_id,
                                evidence_path=str(self.logger.log_path),
                                error=RunError(
                                    code="recovery_failed",
                                    message=(
                                        f"Human intervention did not clear recoverable "
                                        f"condition: {rule.code}"
                                    ),
                                    step_id=step.id,
                                    recoverable=False,
                                ),
                            )

                self.policy.assert_action_allowed(step.kind)

                if step.risk.value == "risky":
                    await self.handoff.intervene(
                        f"Risky step requires human execution/approval: {step.target.description if step.target else step.id}",
                        obs,
                        current_step=step.id,
                    )
                    if not self.handoff.interactive:
                        return RunResult(
                            status=RunStatus.ESCALATED,
                            run_id=self.run_id,
                            evidence_path=str(self.logger.log_path),
                        )
                    self.logger.emit("step_completed_by_human", step_id=step.id, reason="risky_action")
                    continue

                self.logger.emit("step_start", step=step.model_dump())
                try:
                    used_strategy = await self._execute_step(step, params, outputs)
                except Exception as first_exc:
                    # Bounded automatic recovery for transient slowness / temporarily unavailable locators.
                    self.logger.emit(
                        "recoverable_retry",
                        step_id=step.id,
                        error=type(first_exc).__name__,
                        message=str(first_exc),
                        attempt=1,
                    )
                    await self.surface.wait(750)
                    try:
                        used_strategy = await self._execute_step(step, params, outputs)
                    except Exception as exc:
                        outcome = await self._detect_business_outcome(artifact)
                        if outcome:
                            return RunResult(
                                status=RunStatus.BUSINESS_OUTCOME,
                                business_outcome=outcome,
                                outputs=outputs,
                                run_id=self.run_id,
                                evidence_path=str(self.logger.log_path),
                            )

                        hard = await self._detect_hard_failure(artifact)
                        if hard:
                            code, description = hard
                            return RunResult(
                                status=RunStatus.FAILURE,
                                outputs=outputs,
                                run_id=self.run_id,
                                evidence_path=str(self.logger.log_path),
                                error=RunError(
                                    code=code,
                                    message=description,
                                    step_id=step.id,
                                    recoverable=False,
                                ),
                            )

                        fail_shot = str(self.logger.screenshot_dir / f"failure-{idx:02d}-{step.id}.png")
                        fail_obs = await self.surface.observe(fail_shot)
                        self.logger.emit(
                            "step_failure",
                            step_id=step.id,
                            error=type(exc).__name__,
                            message=str(exc),
                            screenshot=fail_shot,
                            observed=fail_obs.visible_text[:1000],
                        )
                        await self.handoff.intervene(
                            f"Replay could not execute {step.id}: {exc}",
                            fail_obs,
                            current_step=step.id,
                        )
                        if not self.handoff.interactive:
                            return RunResult(
                                status=RunStatus.ESCALATED,
                                outputs=outputs,
                                run_id=self.run_id,
                                evidence_path=str(self.logger.log_path),
                                error=RunError(
                                    code="step_execution_failed",
                                    message=str(exc),
                                    step_id=step.id,
                                    expected=step.target.description if step.target else step.kind.value,
                                    observed=fail_obs.visible_text[:500],
                                    recoverable=True,
                                ),
                            )
                        # Human is instructed to complete the blocked step in the same live session.
                        # Resume with the next deterministic step; downstream assertions/checkpoint
                        # will catch an incomplete intervention.
                        self.logger.emit("step_completed_by_human", step_id=step.id, reason="automation_failure")
                        continue

                self.logger.emit("step_success", step_id=step.id, locator_strategy=used_strategy)

            outcome = await self._detect_business_outcome(artifact)
            if outcome:
                return RunResult(
                    status=RunStatus.BUSINESS_OUTCOME,
                    business_outcome=outcome,
                    outputs=outputs,
                    run_id=self.run_id,
                    evidence_path=str(self.logger.log_path),
                )

            hard = await self._detect_hard_failure(artifact)
            if hard:
                code, description = hard
                return RunResult(
                    status=RunStatus.FAILURE,
                    outputs=outputs,
                    run_id=self.run_id,
                    evidence_path=str(self.logger.log_path),
                    error=RunError(code=code, message=description, recoverable=False),
                )

            if not await self._condition_matches(artifact.success_checkpoint):
                obs = await self.surface.observe(str(self.logger.screenshot_dir / "checkpoint-failure.png"))
                return RunResult(
                    status=RunStatus.FAILURE,
                    outputs=outputs,
                    run_id=self.run_id,
                    evidence_path=str(self.logger.log_path),
                    error=RunError(
                        code="checkpoint_failed",
                        message="Replay completed steps but final checkpoint did not match.",
                        expected=artifact.success_checkpoint.model_dump_json(),
                        observed=obs.visible_text[:500],
                        recoverable=False,
                    ),
                )

            self.logger.emit("replay_success", outputs=outputs)
            return RunResult(
                status=RunStatus.SUCCESS,
                outputs=outputs,
                run_id=self.run_id,
                evidence_path=str(self.logger.log_path),
            )
        except PolicyViolation as exc:
            self.logger.emit("policy_failure", message=str(exc))
            return RunResult(
                status=RunStatus.FAILURE,
                run_id=self.run_id,
                evidence_path=str(self.logger.log_path),
                error=RunError(code="policy_violation", message=str(exc), recoverable=False),
            )
        finally:
            await self.surface.close()
