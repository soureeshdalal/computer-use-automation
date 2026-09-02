"""Tests for capability contract, replay, safety, and handoff."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from computer_use.discovery.agent import DiscoveryAgent, save_artifact
from computer_use.escalation.handoff import HandoffController, HandoffMode
from computer_use.llm.openai_planner import MockPlanner
from computer_use.models import (
    ArtifactAction,
    ArtifactStep,
    CapabilityArtifact,
    DiscoveryProvenance,
    FieldSchema,
    FieldType,
    LocatorCandidate,
    RunStatus,
    TargetApp,
)
from computer_use.observability.logger import RunLogger
from computer_use.replay.engine import ReplayEngine
from computer_use.replay.outcomes import detect_business_outcome
from computer_use.safety.policy import PolicyEngine, PolicyViolation, redact_text
from computer_use.surfaces.playwright_surface import PlaywrightSurface

ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "policy.json"
BASE_URL = "http://127.0.0.1:8765"


@pytest.fixture(scope="session")
def demo_server():
    proc = subprocess.Popen(
        [sys.executable, "-m", "demo_app.app"],
        cwd=ROOT,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(2)
    yield proc
    proc.terminate()
    proc.wait(timeout=5)


def test_artifact_contract_validation():
    artifact = CapabilityArtifact(
        name="demo",
        description="demo",
        goal_template="goal {{member_id}}",
        target=TargetApp(entry_url=f"{BASE_URL}/login"),
        inputs={
            "member_id": FieldSchema(name="member_id", type=FieldType.STRING),
        },
        outputs={
            "savings_balance": FieldSchema(name="savings_balance", type=FieldType.STRING),
        },
        steps=[
            ArtifactStep(
                id="step_1",
                action=ArtifactAction.EXTRACT,
                targets=[
                    LocatorCandidate(
                        strategy="css_attr",
                        attribute="id",
                        value="savings-balance",
                        rationale="balance",
                    )
                ],
                output_name="savings_balance",
            )
        ],
        success_checkpoint="Member Details",
    )
    assert artifact.name == "demo"


def test_business_outcome_detection():
    outcome = detect_business_outcome("No record found for the member number entered.")
    assert outcome is not None
    assert outcome.code == "MEMBER_NOT_FOUND"


def test_policy_blocks_host():
    policy = PolicyEngine(POLICY)
    with pytest.raises(PolicyViolation):
        policy.check_url("http://evil.example.com")


def test_redaction():
    assert "[REDACTED_SECRET]" in redact_text("token sk-123456789012345678901234567890")


def test_mock_discovery_and_replay(demo_server, tmp_path):
    policy = PolicyEngine(POLICY)
    logger = RunLogger(tmp_path, "discovery")
    surface = PlaywrightSurface(policy, headless=True, base_url=BASE_URL)
    planner = MockPlanner()
    inputs = {
        "member_id": FieldSchema(name="member_id", type=FieldType.STRING),
        "operator_password": FieldSchema(name="operator_password", type=FieldType.STRING),
    }
    outputs = {
        "savings_balance": FieldSchema(name="savings_balance", type=FieldType.STRING),
    }
    agent = DiscoveryAgent(surface, planner, policy, logger)
    artifact, discovery_result = agent.run(
        goal="Look up member 12345",
        goal_template="Look up member {{member_id}}",
        entry_url=f"{BASE_URL}/login",
        inputs=inputs,
        outputs=outputs,
        input_values={"member_id": "12345", "operator_password": "demo"},
        capability_name="lookup_member_balance",
        description="Lookup balance",
    )
    assert discovery_result.status == RunStatus.SUCCESS
    assert artifact is not None
    assert planner.call_count > 0

    artifact_path = tmp_path / "artifact.json"
    save_artifact(artifact, artifact_path)

    replay_logger = RunLogger(tmp_path, "replay")
    replay_surface = PlaywrightSurface(policy, headless=True, base_url=BASE_URL)
    engine = ReplayEngine(
        replay_surface,
        policy,
        replay_logger,
        handoff=HandoffController(mode=HandoffMode.AUTO, evidence_dir=replay_logger.run_dir),
    )
    replay_result = engine.run(
        artifact,
        {"member_id": "54321", "operator_password": "demo"},
    )
    assert replay_result.status == RunStatus.SUCCESS
    assert replay_result.llm_calls == 0
    assert "savings_balance" in replay_result.outputs


def test_replay_member_not_found(demo_server, tmp_path):
    artifact = _sample_artifact()
    policy = PolicyEngine(POLICY)
    logger = RunLogger(tmp_path, "replay")
    surface = PlaywrightSurface(policy, headless=True, base_url=BASE_URL)
    engine = ReplayEngine(surface, policy, logger)
    result = engine.run(artifact, {"member_id": "99999", "operator_password": "demo"})
    assert result.status == RunStatus.BUSINESS_OUTCOME
    assert result.business_outcome.code == "MEMBER_NOT_FOUND"
    assert result.llm_calls == 0


def _sample_artifact() -> CapabilityArtifact:
    path = ROOT / "capabilities" / "lookup_member_balance.json"
    if path.exists():
        return CapabilityArtifact.model_validate_json(path.read_text(encoding="utf-8"))
    pytest.skip("Sample artifact not generated yet")
