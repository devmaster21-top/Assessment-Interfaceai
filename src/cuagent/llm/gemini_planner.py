from __future__ import annotations

import json
import os
from textwrap import dedent

from google import genai
from google.genai import types

from cuagent.models import AgentDecision, Observation


class GeminiPlanner:
    """Gemini is used only during discovery, never during deterministic replay."""

    def __init__(self, model: str | None = None):
        self.client = genai.Client()
        self.model = model or os.getenv(
            "GEMINI_MODEL",
            "gemini-3.5-flash-lite",
        )

    def decide(
        self,
        goal: str,
        observation: Observation,
        params: dict[str, str],
        prior_summary: list[str],
    ) -> AgentDecision:

        controls = [
            {
                "index": c.index,
                "role": c.role,
                "name": c.accessible_name,
                "label": c.label,
                "text": c.text,
                "type": c.input_type,
            }
            for c in observation.controls
        ]

        prompt = dedent(
            f"""
            You are controlling a business application through a constrained
            computer-use adapter.

            Goal: {goal}

            Invocation parameters:
            {json.dumps(params)}

            Current URL:
            {observation.url}

            Page title:
            {observation.title}

            Visible text:
            {observation.visible_text[:7000]}

            Visible controls, referenced by index:
            {json.dumps(controls, ensure_ascii=False)}

            Previous action summaries:
            {json.dumps(prior_summary[-6:])}

            Decide exactly one next action.

            Rules:

            - Take exactly one action per turn.
            - Use target_index only from the controls above.
            - When typing an invocation parameter, set value_from to
              the parameter name and leave value null.
            - Use extract when the goal asks to read a value.
            - output_name should be stable snake_case.
            - Do not click destructive, money-moving, delete,
              suspend, or irreversible controls.
            - Mark success only when the current observation visibly proves the full goal
  is complete. Never infer completion from navigation state alone.
            - success_marker must be stable visible text and should
              not contain dynamic PII or parameter values.
            - Validation errors, permission errors, not-found states,
              expired sessions, or other blocking states should return
              blocked.
            - NEVER return status="success" if the requested output value is not visibly present
              in the current observation.

            - If the goal asks to read or extract a value, first navigate until that value is
            visible, then return an extract action.

            - An extract action must use target_index pointing to a visible control or element
            that contains the requested value.

            - Do not assume a value exists based on a link or button label.

            - "Member Detail" alone does NOT satisfy a goal asking for a savings balance.

            - For goals requiring outputs, success is allowed only after all requested outputs
            have been extracted.
            """
        ).strip()

        response = self.client.models.generate_content(
            model=self.model,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_mime_type="application/json",
                response_schema=AgentDecision,
                temperature=0.1,
            ),
        )

        return AgentDecision.model_validate_json(response.text)