"""FastAPI catalog for agent-facing capability invocation."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from computer_use.config import CAPABILITIES_DIR, POLICY_PATH
from computer_use.escalation.handoff import HandoffController, HandoffMode
from computer_use.models import CapabilityArtifact, RunResult
from computer_use.observability.logger import RunLogger
from computer_use.replay.engine import ReplayEngine
from computer_use.safety.policy import PolicyEngine
from computer_use.surfaces.playwright_surface import PlaywrightSurface


class InvokeRequest(BaseModel):
    inputs: dict[str, str] = Field(default_factory=dict)
    headless: bool = True


def create_app(capabilities_dir: Path | None = None) -> FastAPI:
    app = FastAPI(title="Capability Catalog", version="1.0.0")
    catalog_dir = capabilities_dir or CAPABILITIES_DIR

    @app.get("/capabilities")
    def list_capabilities() -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for path in sorted(catalog_dir.glob("*.json")):
            artifact = CapabilityArtifact.model_validate_json(path.read_text(encoding="utf-8"))
            items.append(
                {
                    "name": artifact.name,
                    "version": artifact.version,
                    "description": artifact.description,
                    "inputs": {k: v.model_dump() for k, v in artifact.inputs.items()},
                    "outputs": {k: v.model_dump() for k, v in artifact.outputs.items()},
                    "path": str(path),
                }
            )
        return items

    @app.post("/capabilities/{name}/invoke")
    def invoke_capability(name: str, body: InvokeRequest) -> dict[str, Any]:
        matches = list(catalog_dir.glob(f"{name}*.json")) + list(catalog_dir.glob("*.json"))
        artifact_path = None
        for path in matches:
            artifact = CapabilityArtifact.model_validate_json(path.read_text(encoding="utf-8"))
            if artifact.name == name:
                artifact_path = path
                break
        if artifact_path is None:
            raise HTTPException(status_code=404, detail=f"Capability '{name}' not found")

        artifact = CapabilityArtifact.model_validate_json(artifact_path.read_text(encoding="utf-8"))
        policy = PolicyEngine(POLICY_PATH)
        logger = RunLogger("evidence/runs", "api-replay")
        surface = PlaywrightSurface(policy, headless=body.headless)
        engine = ReplayEngine(
            surface,
            policy,
            logger,
            handoff=HandoffController(mode=HandoffMode.AUTO, evidence_dir=logger.run_dir),
        )
        result: RunResult = engine.run(artifact, body.inputs)
        return json.loads(result.model_dump_json())

    return app


app = create_app()
