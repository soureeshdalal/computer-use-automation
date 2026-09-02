"""CLI entry points for discovery and replay."""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

from computer_use.config import (
    CAPABILITIES_DIR,
    DEMO_APP_PORT,
    DEMO_APP_URL,
    EVIDENCE_DIR,
    OPENAI_API_KEY,
    OPENAI_MODEL,
    POLICY_PATH,
)
from computer_use.discovery.agent import DiscoveryAgent, save_artifact
from computer_use.escalation.handoff import HandoffController, HandoffMode
from computer_use.llm.openai_planner import MockPlanner, OpenAIPlanner
from computer_use.models import CapabilityArtifact, FieldSchema, FieldType
from computer_use.observability.logger import RunLogger
from computer_use.replay.engine import ReplayEngine
from computer_use.safety.policy import PolicyEngine
from computer_use.surfaces.playwright_surface import PlaywrightSurface


def _parse_params(pairs: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs:
        key, value = pair.split("=", 1)
        params[key] = value
    return params


def cmd_discover(args: argparse.Namespace) -> int:
    params = _parse_params(args.param)
    policy = PolicyEngine(POLICY_PATH)
    logger = RunLogger(EVIDENCE_DIR, "discovery")
    surface = PlaywrightSurface(policy, headless=args.headless, base_url=DEMO_APP_URL)

    if args.planner == "mock":
        planner = MockPlanner()
    else:
        if not OPENAI_API_KEY:
            print("OPENAI_API_KEY is required for live discovery.", file=sys.stderr)
            return 1
        planner = OpenAIPlanner(model=OPENAI_MODEL, api_key=OPENAI_API_KEY)

    inputs = {
        "member_id": FieldSchema(
            name="member_id",
            type=FieldType.STRING,
            description="Member number to look up",
        ),
        "operator_password": FieldSchema(
            name="operator_password",
            type=FieldType.STRING,
            description="Operator console password",
            required=True,
        ),
    }
    outputs = {
        "savings_balance": FieldSchema(
            name="savings_balance",
            type=FieldType.STRING,
            description="Current savings balance text",
        )
    }
    if "operator_password" not in params:
        params["operator_password"] = "demo"

    goal_template = args.goal
    goal = goal_template.replace("{{member_id}}", params["member_id"])

    agent = DiscoveryAgent(surface, planner, policy, logger)
    artifact, result = agent.run(
        goal=goal,
        goal_template=goal_template,
        entry_url=f"{DEMO_APP_URL}/login",
        inputs=inputs,
        outputs=outputs,
        input_values=params,
        capability_name=args.name,
        description="Look up a member and read the savings balance.",
    )

    print(json.dumps(result.model_dump(), indent=2))
    if artifact is None:
        return 1

    output_path = Path(args.output)
    save_artifact(artifact, output_path)
    print(f"Saved artifact to {output_path}")
    return 0


def cmd_replay(args: argparse.Namespace) -> int:
    params = _parse_params(args.input)
    artifact = CapabilityArtifact.model_validate_json(
        Path(args.artifact).read_text(encoding="utf-8")
    )
    policy = PolicyEngine(POLICY_PATH)
    logger = RunLogger(EVIDENCE_DIR, "replay")
    surface = PlaywrightSurface(policy, headless=args.headless, base_url=DEMO_APP_URL)
    mode = HandoffMode.INTERACTIVE if args.human_mode == "interactive" else HandoffMode.AUTO
    handoff = HandoffController(mode=mode, evidence_dir=logger.run_dir)
    engine = ReplayEngine(surface, policy, logger, handoff=handoff)
    result = engine.run(artifact, params)
    print(json.dumps(result.model_dump(), indent=2))
    return 0 if result.status.value in {"success", "business_outcome"} else 1


def cmd_serve(_: argparse.Namespace) -> int:
    from demo_app.app import main

    main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="computer_use")
    sub = parser.add_subparsers(dest="command", required=True)

    discover = sub.add_parser("discover", help="Run LLM discovery")
    discover.add_argument("--goal", required=True)
    discover.add_argument("--param", action="append", default=[])
    discover.add_argument("--name", required=True)
    discover.add_argument("--output", default=str(CAPABILITIES_DIR / "capability.json"))
    discover.add_argument("--planner", choices=["openai", "mock"], default="openai")
    discover.add_argument("--headless", action="store_true")
    discover.set_defaults(func=cmd_discover)

    replay = sub.add_parser("replay", help="Replay a saved artifact")
    replay.add_argument("artifact")
    replay.add_argument("--input", action="append", default=[])
    replay.add_argument("--headless", action="store_true")
    replay.add_argument(
        "--human-mode",
        choices=["auto", "interactive"],
        default="auto",
    )
    replay.set_defaults(func=cmd_replay)

    serve = sub.add_parser("serve", help="Run demo legacy app")
    serve.set_defaults(func=cmd_serve)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
