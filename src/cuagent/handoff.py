from __future__ import annotations

import json
import uuid
from pathlib import Path

from cuagent.evidence import EvidenceLogger
from cuagent.models import InterventionRequest, Observation


class HumanHandoff:
    """Minimal real control transfer for a headed browser session.

    Automation pauses but keeps the exact browser context alive. The operator can use
    the open browser window, then presses Enter in the terminal to return control.
    """

    def __init__(self, logger: EvidenceLogger, interactive: bool = True):
        self.logger = logger
        self.interactive = interactive
        self.owner = "automation"

    async def intervene(self, reason: str, observation: Observation, current_step: str | None = None) -> InterventionRequest:
        self.owner = "human"
        req = InterventionRequest(
            intervention_id=str(uuid.uuid4()),
            run_id=self.logger.run_id,
            reason=reason,
            current_step=current_step,
            screenshot_path=observation.screenshot_path,
            state_summary=f"{observation.title} | {observation.url} | {observation.visible_text[:500]}",
            control_owner="human",
        )
        path = self.logger.intervention_dir / f"{req.intervention_id}.json"
        path.write_text(req.model_dump_json(indent=2), encoding="utf-8")
        self.logger.emit("human_handoff_started", intervention=req.model_dump())
        if not self.interactive:
            return req
        print("\n=== HUMAN CONTROL REQUESTED ===")
        print(reason)
        print("The same browser session remains open. Perform the needed manual action there.")
        note = input("When done, briefly describe what you changed (or just press Enter): ").strip()
        self.owner = "automation"
        self.logger.emit(
            "human_handoff_resumed",
            intervention_id=req.intervention_id,
            human_action_note=note or "manual intervention completed",
        )
        return req
