from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv

from cuagent.discovery import DiscoveryRunner
from cuagent.llm.gemini_planner import GeminiPlanner
from cuagent.models import ActionKind, CapabilityArtifact
from cuagent.policy import PolicyConfig, SafetyPolicy
from cuagent.recorder import ArtifactRecorder, slugify
from cuagent.replay import ReplayRunner
from cuagent.surface.playwright_surface import PlaywrightSurface
from cuagent.target_profile import demo_business_outcomes, demo_hard_failures, demo_recoverable_conditions


def parse_params(values: list[str]) -> dict[str, str]:
    result = {}
    for item in values:
        if "=" not in item:
            raise SystemExit(f"Invalid --param '{item}', expected key=value")
        key, value = item.split("=", 1)
        result[key] = value
    return result


def policy_for(entry_point: str) -> SafetyPolicy:
    host = urlparse(entry_point).hostname or "localhost"
    return SafetyPolicy(
        PolicyConfig(
            allowed_hosts={host},
            allowed_actions={ActionKind.CLICK, ActionKind.TYPE, ActionKind.EXTRACT, ActionKind.WAIT},
        )
    )


async def discover(args: argparse.Namespace) -> int:
    params = parse_params(args.param)
    surface = PlaywrightSurface(headed=args.headed, slow_mo=args.slow_mo)
    planner = GeminiPlanner(model=args.model)
    recorder = ArtifactRecorder(
        surface=surface,
        capability_id=args.capability_id or slugify(args.goal),
        name=args.name or "Lookup member savings balance",
        description=args.goal,
        target_app="Legacy Credit Union Demo",
        entry_point=args.target,
        allowed_hosts=[urlparse(args.target).hostname or "localhost"],
        params=params,
        business_outcomes=demo_business_outcomes(),
        recoverable_conditions=demo_recoverable_conditions(),
        hard_failures=demo_hard_failures(),
    )
    runner = DiscoveryRunner(
        surface=surface,
        planner=planner,
        policy=policy_for(args.target),
        recorder=recorder,
        evidence_root=Path(args.evidence),
        max_steps=args.max_steps,
        human_interactive=not args.noninteractive,
    )
    result = await runner.run(args.goal, params, Path(args.artifact))
    print(result.model_dump_json(indent=2))
    return 0 if result.status.value == "success" else 1


async def replay(args: argparse.Namespace) -> int:
    artifact = CapabilityArtifact.model_validate_json(Path(args.artifact).read_text(encoding="utf-8"))
    params = parse_params(args.param)
    surface = PlaywrightSurface(headed=args.headed, slow_mo=args.slow_mo)
    runner = ReplayRunner(
        surface=surface,
        policy=policy_for(artifact.entry_point),
        evidence_root=Path(args.evidence),
        human_interactive=not args.noninteractive,
    )
    result = await runner.run(artifact, params)
    print(result.model_dump_json(indent=2))
    return 0 if result.status.value in {"success", "business_outcome"} else 1


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Discover and replay computer-use capabilities")
    sub = p.add_subparsers(dest="command", required=True)

    d = sub.add_parser("discover", help="Run a genuine LLM-driven discovery session")
    d.add_argument("--goal", required=True)
    d.add_argument("--target", default="http://127.0.0.1:8000/")
    d.add_argument("--param", action="append", default=[])
    d.add_argument("--artifact", default="evidence/artifacts/lookup_member_savings.v1.json")
    d.add_argument("--evidence", default="evidence")
    d.add_argument("--model", default=None)
    d.add_argument("--capability-id", default=None)
    d.add_argument("--name", default=None)
    d.add_argument("--max-steps", type=int, default=15)
    d.add_argument("--headed", action="store_true")
    d.add_argument("--slow-mo", type=int, default=0)
    d.add_argument("--noninteractive", action="store_true")

    r = sub.add_parser("replay", help="Replay a saved capability with no LLM decisions")
    r.add_argument("--artifact", required=True)
    r.add_argument("--param", action="append", default=[])
    r.add_argument("--evidence", default="evidence")
    r.add_argument("--headed", action="store_true")
    r.add_argument("--slow-mo", type=int, default=0)
    r.add_argument("--noninteractive", action="store_true")
    return p


def main() -> None:
    load_dotenv()
    args = build_parser().parse_args()
    code = asyncio.run(discover(args) if args.command == "discover" else replay(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
