from __future__ import annotations

import asyncio
import json
import time
import uuid
from pathlib import Path

from cuagent.evidence import EvidenceLogger
from cuagent.handoff import HumanHandoff
from cuagent.llm.gemini_planner import GeminiPlanner
from cuagent.models import ActionKind, CapabilityArtifact, RunResult, RunStatus
from cuagent.policy import PolicyViolation, SafetyPolicy
from cuagent.recorder import ArtifactRecorder
from cuagent.surface.playwright_surface import PlaywrightSurface


class DiscoveryRunner:
    def __init__(
        self,
        surface: PlaywrightSurface,
        planner: GeminiPlanner,
        policy: SafetyPolicy,
        recorder: ArtifactRecorder,
        evidence_root: Path,
        max_steps: int = 15,
        timeout_s: int = 300,
        human_interactive: bool = True,
    ):
        self.surface = surface
        self.planner = planner
        self.policy = policy
        self.recorder = recorder
        self.max_steps = max_steps
        self.timeout_s = timeout_s
        self.run_id = str(uuid.uuid4())[:8]
        self.logger = EvidenceLogger(evidence_root, self.run_id, "discovery")
        self.handoff = HumanHandoff(self.logger, interactive=human_interactive)

    async def _handoff(
        self,
        reason: str,
        observation,
        current_step: str | None = None,
    ) -> float:
        started = time.monotonic()

        await self.handoff.intervene(
            reason,
            observation,
            current_step=current_step,
        )

        return time.monotonic() - started

    async def run(self, goal: str, params: dict[str, str], artifact_path: Path) -> RunResult:
        started = time.monotonic()
        paused_time = 0.0
        prior: list[str] = []
        extracted: dict[str, str] = {}
        state_fingerprints: list[str] = []
        try:
            await self.surface.start(self.recorder.entry_point)
            for step_no in range(1, self.max_steps + 1):
                active_elapsed = time.monotonic() - started - paused_time

                if active_elapsed > self.timeout_s:
                    raise TimeoutError("discovery timeout exceeded")

                shot = str(self.logger.screenshot_dir / f"step-{step_no:02d}.png")
                obs = await self.surface.observe(shot)
                self.policy.assert_url_allowed(obs.url)
                self.logger.emit(
                    "observation",
                    step=step_no,
                    url=obs.url,
                    title=obs.title,
                    text_preview=obs.visible_text[:1000],
                    controls=[c.model_dump() for c in obs.controls],
                    screenshot=shot,
                )

                fingerprint = f"{obs.url}|{obs.visible_text[:700]}"
                state_fingerprints.append(fingerprint)
                if len(state_fingerprints) >= 3 and len(set(state_fingerprints[-3:])) == 1:
                    paused_time += await self._handoff("Discovery is stuck in the same state for three turns.", obs)

                decision = await asyncio.to_thread(self.planner.decide, goal, obs, params, prior)
                self.logger.emit("llm_decision", step=step_no, decision=decision.model_dump())
                prior.append(f"{decision.status}: {decision.reason}")

                if decision.status == "blocked":
                    paused_time += await self._handoff(decision.reason, obs)
                    continue

                action = decision.action

                if not action:
                    if decision.status == "success" and extracted:
                        marker = decision.success_marker or obs.title
                        artifact = self.recorder.build(marker)

                        artifact_path.parent.mkdir(parents=True, exist_ok=True)
                        artifact_path.write_text(
                            artifact.model_dump_json(indent=2),
                            encoding="utf-8",
                        )

                        self.logger.emit(
                            "artifact_saved",
                            path=str(artifact_path),
                            artifact=artifact.model_dump(),
                        )

                        return RunResult(
                            status=RunStatus.SUCCESS,
                            outputs=extracted,
                            run_id=self.run_id,
                            evidence_path=str(self.logger.log_path),
                        )

                    if decision.status == "success":
                        prior.append(
                            "Success rejected: requested output has not been extracted yet."
                        )
                        continue

                    paused_time += await self._handoff(
                        "LLM returned continue with no action.",
                        obs,
                    )
                    continue

                action_kind = ActionKind(action.kind)
                if action_kind == ActionKind.EXTRACT and action.target_index is None:
                    prior.append(
                        "Invalid extract action: choose a visible target_index containing the requested value."
                    )
                    continue
                self.policy.assert_action_allowed(action_kind)
                control = None
                if action.target_index is not None:
                    control = next((c for c in obs.controls if c.index == action.target_index), None)
                    if control is None:
                        paused_time += await self._handoff(
                            f"LLM selected unknown target index {action.target_index}.", obs
                        )
                        continue

                if action_kind == ActionKind.TYPE:
                    self.policy.assert_safe_input(control)
                risk = self.policy.classify_control(control)
                if risk.value == "risky":
                    paused_time += await self._handoff(
                        f"Policy requires human approval for risky control: {control.accessible_name if control else 'unknown'}",
                        obs,
                    )
                    continue

                recorded = self.recorder.record(action, control, risk)
                self.logger.emit("action_start", step_id=recorded.id, action=recorded.model_dump())

                if action_kind == ActionKind.CLICK:
                    assert control
                    await self.surface.click_control(control)
                elif action_kind == ActionKind.TYPE:
                    assert control
                    value = params[action.value_from] if action.value_from else (action.value or "")
                    await self.surface.type_control(control, value)
                elif action_kind == ActionKind.EXTRACT:
                    assert control
                    value = await self.surface.extract_control(control)
                    extracted[action.output_name or recorded.output_name or "output"] = value
                    self.logger.emit("output_extracted", name=action.output_name, value=value)
                elif action_kind == ActionKind.WAIT:
                    await self.surface.wait(action.wait_ms or 500)
                self.logger.emit("action_end", step_id=recorded.id)
                if decision.status == "success":
                    if not extracted:
                        prior.append(
                            "Success rejected: the requested output has not been extracted yet."
                        )
                        continue

                    marker = decision.success_marker or obs.title
                    artifact = self.recorder.build(marker)

                    artifact_path.parent.mkdir(parents=True, exist_ok=True)
                    artifact_path.write_text(
                        artifact.model_dump_json(indent=2),
                        encoding="utf-8",
                    )

                    self.logger.emit(
                        "artifact_saved",
                        path=str(artifact_path),
                        artifact=artifact.model_dump(),
                    )

                    return RunResult(
                        status=RunStatus.SUCCESS,
                        outputs=extracted,
                        run_id=self.run_id,
                        evidence_path=str(self.logger.log_path),
                    )

            last_obs = await self.surface.observe(str(self.logger.screenshot_dir / "max-steps.png"))
            paused_time += await self._handoff("Maximum discovery steps reached.", last_obs)
            return RunResult(status=RunStatus.ESCALATED, run_id=self.run_id, evidence_path=str(self.logger.log_path))
        except (PolicyViolation, TimeoutError, Exception) as exc:
            self.logger.emit("discovery_failed", error=type(exc).__name__, message=str(exc))
            return RunResult(
                status=RunStatus.FAILURE,
                run_id=self.run_id,
                evidence_path=str(self.logger.log_path),
                error={"code": type(exc).__name__, "message": str(exc)},
            )
        finally:
            await self.surface.close()
