"""Pydantic models for capability artifacts and run results."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class FieldType(str, Enum):
    STRING = "string"
    NUMBER = "number"
    BOOLEAN = "boolean"


class FieldSchema(BaseModel):
    name: str
    type: FieldType = FieldType.STRING
    description: str = ""
    required: bool = True


class LocatorCandidate(BaseModel):
    strategy: Literal["role_name", "label", "placeholder", "text", "css_attr"]
    role: str | None = None
    name: str | None = None
    label: str | None = None
    placeholder: str | None = None
    text: str | None = None
    attribute: str | None = None
    value: str | None = None
    rationale: str = ""


class ArtifactAction(str, Enum):
    CLICK = "click"
    TYPE = "type"
    SELECT = "select"
    NAVIGATE = "navigate"
    EXTRACT = "extract"
    WAIT = "wait"
    PRESS = "press"


class ArtifactStep(BaseModel):
    id: str
    action: ArtifactAction
    targets: list[LocatorCandidate] = Field(default_factory=list)
    value_template: str | None = None
    output_name: str | None = None
    risky: bool = False
    notes: str = ""


class TargetApp(BaseModel):
    vendor: str = "demo-cu-core"
    app_name: str = "Member Servicing Console"
    entry_url: str
    version: str = "1.0"


class DiscoveryProvenance(BaseModel):
    planner: str
    model: str
    recorded_at: str
    discovery_run_id: str
    llm_calls: int = 0


class CapabilityArtifact(BaseModel):
    schema_version: str = "1.0"
    name: str
    version: str = "1.0.0"
    description: str
    goal_template: str
    target: TargetApp
    inputs: dict[str, FieldSchema]
    outputs: dict[str, FieldSchema]
    steps: list[ArtifactStep]
    success_checkpoint: str
    allowlist: list[str] = Field(default_factory=list)
    provenance: DiscoveryProvenance | None = None

    @field_validator("steps")
    @classmethod
    def steps_non_empty(cls, value: list[ArtifactStep]) -> list[ArtifactStep]:
        if not value:
            raise ValueError("capability must contain at least one step")
        return value

    @model_validator(mode="after")
    def validate_contract(self) -> CapabilityArtifact:
        step_ids = [step.id for step in self.steps]
        if len(step_ids) != len(set(step_ids)):
            raise ValueError("step ids must be unique")

        input_names = set(self.inputs)
        output_names = set(self.outputs)

        for step in self.steps:
            if step.value_template:
                for token in _template_tokens(step.value_template):
                    if token not in input_names:
                        raise ValueError(
                            f"step {step.id} references undeclared input {token}"
                        )
            if step.action == ArtifactAction.EXTRACT:
                if not step.output_name:
                    raise ValueError(f"extract step {step.id} requires output_name")
                if step.output_name not in output_names:
                    raise ValueError(
                        f"extract step {step.id} references undeclared output"
                    )

        extract_outputs = {
            step.output_name
            for step in self.steps
            if step.action == ArtifactAction.EXTRACT and step.output_name
        }
        missing = output_names - extract_outputs
        if missing:
            raise ValueError(f"outputs missing extract steps: {sorted(missing)}")

        if not self.success_checkpoint.strip():
            raise ValueError("success_checkpoint cannot be empty")
        return self


def _template_tokens(template: str) -> list[str]:
    tokens: list[str] = []
    start = 0
    while True:
        open_idx = template.find("{{", start)
        if open_idx == -1:
            break
        close_idx = template.find("}}", open_idx + 2)
        if close_idx == -1:
            break
        tokens.append(template[open_idx + 2 : close_idx].strip())
        start = close_idx + 2
    return tokens


class RunStatus(str, Enum):
    SUCCESS = "success"
    BUSINESS_OUTCOME = "business_outcome"
    FAILURE = "failure"
    ESCALATED = "escalated"


class FailureDetail(BaseModel):
    code: str
    message: str
    step_id: str | None = None
    expected: str | None = None
    observed: str | None = None
    evidence_path: str | None = None


class BusinessOutcome(BaseModel):
    code: str
    message: str


class RunResult(BaseModel):
    status: RunStatus
    capability_name: str
    run_id: str
    llm_calls: int = 0
    outputs: dict[str, Any] = Field(default_factory=dict)
    business_outcome: BusinessOutcome | None = None
    failure: FailureDetail | None = None
    recovered_conditions: list[str] = Field(default_factory=list)
    evidence_dir: str | None = None
    duration_ms: int = 0


class InterventionRequest(BaseModel):
    request_id: str
    capability_name: str
    goal: str
    step_id: str | None
    reason: str
    url: str | None = None
    screenshot_path: str | None = None
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
