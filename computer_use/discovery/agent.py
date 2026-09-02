"""LangGraph-based discovery loop and artifact recording."""

from __future__ import annotations

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from computer_use.llm.openai_planner import MockPlanner, OpenAIPlanner, Planner, PlannedAction
from computer_use.models import (
    ArtifactAction,
    ArtifactStep,
    CapabilityArtifact,
    DiscoveryProvenance,
    FailureDetail,
    FieldSchema,
    LocatorCandidate,
    RunResult,
    RunStatus,
    TargetApp,
    utc_now_iso,
)
from computer_use.observability.logger import RunLogger
from computer_use.safety.policy import PolicyEngine, PolicyViolation
from computer_use.surfaces.playwright_surface import PlaywrightSurface


class DiscoveryState(TypedDict, total=False):
    step_count: int
    done: bool
    failed: bool
    failure_message: str
    outputs: dict[str, Any]


class DiscoveryAgent:
    def __init__(
        self,
        surface: PlaywrightSurface,
        planner: Planner,
        policy: PolicyEngine,
        logger: RunLogger,
    ) -> None:
        self.surface = surface
        self.planner = planner
        self.policy = policy
        self.logger = logger
        self.recorded_steps: list[ArtifactStep] = []
        self.goal_template = ""
        self.inputs: dict[str, FieldSchema] = {}
        self.outputs: dict[str, FieldSchema] = {}
        self.input_values: dict[str, str] = {}

    def run(
        self,
        goal: str,
        goal_template: str,
        entry_url: str,
        inputs: dict[str, FieldSchema],
        outputs: dict[str, FieldSchema],
        input_values: dict[str, str],
        capability_name: str,
        description: str,
    ) -> tuple[CapabilityArtifact | None, RunResult]:
        self.goal_template = goal_template
        self.inputs = inputs
        self.outputs = outputs
        self.input_values = input_values
        self.recorded_steps = []

        graph = StateGraph(DiscoveryState)
        graph.add_node("act", self._act_node)
        graph.set_entry_point("act")
        graph.add_conditional_edges(
            "act",
            self._should_continue,
            {"continue": "act", "stop": END},
        )
        app = graph.compile()
        state: DiscoveryState = {"step_count": 0, "done": False, "failed": False, "outputs": {}}

        self.surface.start()
        try:
            self.surface.navigate(entry_url)
            final_state = app.invoke(state)
            trace_path = str(self.logger.trace_path())
            self.surface.stop(trace_path=trace_path)

            if final_state.get("failed"):
                return None, RunResult(
                    status=RunStatus.FAILURE,
                    capability_name=capability_name,
                    run_id=self.logger.run_id,
                    llm_calls=self.planner.call_count,
                    failure=FailureDetail(
                        code="DISCOVERY_FAILED",
                        message=final_state.get("failure_message", "Discovery failed"),
                    ),
                    evidence_dir=str(self.logger.run_dir),
                )

            host_port = entry_url.split("//")[1].split("/")[0]
            artifact = CapabilityArtifact(
                name=capability_name,
                description=description,
                goal_template=goal_template,
                target=TargetApp(
                    vendor="demo-cu-core",
                    app_name="Member Servicing Console",
                    entry_url=entry_url,
                    version="1.0",
                ),
                inputs=inputs,
                outputs=outputs,
                steps=self.recorded_steps,
                success_checkpoint="Member Details",
                allowlist=[f"http://{host_port}/*"],
                provenance=DiscoveryProvenance(
                    planner=type(self.planner).__name__,
                    model=getattr(self.planner, "model", "mock"),
                    recorded_at=utc_now_iso(),
                    discovery_run_id=self.logger.run_id,
                    llm_calls=self.planner.call_count,
                ),
            )
            return artifact, RunResult(
                status=RunStatus.SUCCESS,
                capability_name=capability_name,
                run_id=self.logger.run_id,
                llm_calls=self.planner.call_count,
                outputs=final_state.get("outputs", {}),
                evidence_dir=str(self.logger.run_dir),
            )
        except Exception as exc:  # noqa: BLE001
            screenshot = self.logger.screenshot_path("failure")
            try:
                self.surface.screenshot(str(screenshot))
            except Exception:
                pass
            try:
                self.surface.stop(trace_path=str(self.logger.trace_path()))
            except Exception:
                pass
            return None, RunResult(
                status=RunStatus.FAILURE,
                capability_name=capability_name,
                run_id=self.logger.run_id,
                llm_calls=self.planner.call_count,
                failure=FailureDetail(
                    code="DISCOVERY_EXCEPTION",
                    message=str(exc),
                    evidence_path=str(screenshot),
                ),
                evidence_dir=str(self.logger.run_dir),
            )

    def _should_continue(self, state: DiscoveryState) -> str:
        if state.get("done") or state.get("failed"):
            return "stop"
        if state.get("step_count", 0) >= self.policy.max_steps:
            state["failed"] = True
            state["failure_message"] = "Max steps exceeded"
            return "stop"
        return "continue"

    def _act_node(self, state: DiscoveryState) -> DiscoveryState:
        state["step_count"] = state.get("step_count", 0) + 1
        observation = self.surface.observe()
        goal = _render_goal(self.goal_template, self.input_values)
        planned = self.planner.plan(goal, observation, state["step_count"])
        if isinstance(self.planner, (OpenAIPlanner, MockPlanner)):
            self.logger.increment_llm_calls()

        planned = self._maybe_override_loop(planned, observation)

        self.logger.log(
            "plan",
            {
                "step": state["step_count"],
                "planned_action": planned.model_dump(),
                "url": observation.url,
            },
        )

        if planned.action == "wait":
            return state

        if planned.action == "done":
            if self.surface.page_contains("Member Details"):
                state["done"] = True
            else:
                state["failed"] = True
                state["failure_message"] = "Done signaled but checkpoint missing"
            return state

        if planned.action == "escalate":
            state["failed"] = True
            state["failure_message"] = planned.reason or "Escalation requested"
            return state

        if not planned.element_id:
            state["failed"] = True
            state["failure_message"] = f"Action {planned.action} missing element_id"
            return state

        try:
            self.policy.check_action(planned.action)
        except PolicyViolation as exc:
            state["failed"] = True
            state["failure_message"] = exc.message
            return state

        element = self.surface._element_map.get(planned.element_id)
        element_label = element.name if element else planned.element_id
        if planned.action == "click" and self.policy.is_risky_action(
            ArtifactAction.CLICK, element_label
        ):
            state["failed"] = True
            state["failure_message"] = f"Risky control blocked: {element_label}"
            return state

        targets = self.surface.build_targets(planned.element_id)
        step_id = f"step_{len(self.recorded_steps) + 1}"

        try:
            if planned.action == "click":
                self.surface.click_element(planned.element_id)
                self.recorded_steps.append(
                    ArtifactStep(
                        id=step_id,
                        action=ArtifactAction.CLICK,
                        targets=targets,
                    )
                )
            elif planned.action == "type":
                raw_text = planned.text or ""
                self.surface.type_element(planned.element_id, raw_text)
                self.recorded_steps.append(
                    ArtifactStep(
                        id=step_id,
                        action=ArtifactAction.TYPE,
                        targets=targets,
                        value_template=_parameterize_text(raw_text, self.input_values),
                    )
                )
            elif planned.action == "extract":
                value = self.surface.extract_by_selector("#savings-balance")
                output_name = planned.output_name or "savings_balance"
                state.setdefault("outputs", {})[output_name] = value
                self.recorded_steps.append(
                    ArtifactStep(
                        id=step_id,
                        action=ArtifactAction.EXTRACT,
                        targets=[
                            LocatorCandidate(
                                strategy="css_attr",
                                attribute="id",
                                value="savings-balance",
                                rationale="Savings balance cell in member detail table.",
                            )
                        ],
                        output_name=output_name,
                    )
                )
                if self.surface.page_contains("Member Details"):
                    state["done"] = True
            else:
                state["failed"] = True
                state["failure_message"] = f"Unsupported planned action: {planned.action}"
        except Exception as exc:  # noqa: BLE001
            state["failed"] = True
            state["failure_message"] = str(exc)
        return state

    def _maybe_override_loop(self, planned: PlannedAction, observation) -> PlannedAction:
        if planned.action != "type" or "/home" not in observation.url:
            return planned
        if not self.recorded_steps:
            return planned
        last = self.recorded_steps[-1]
        if last.action != ArtifactAction.TYPE:
            return planned
        for element in observation.elements:
            if "Search Member Records" in element.name:
                return PlannedAction(
                    action="click",
                    element_id=element.element_id,
                    reason="Loop guard: member id already entered, click search.",
                )
        return planned


def save_artifact(artifact: CapabilityArtifact, path: str | Path) -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(artifact.model_dump_json(indent=2), encoding="utf-8")
    return target


def _render_goal(template: str, values: dict[str, str]) -> str:
    result = template
    for key, value in values.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result


def _parameterize_text(text: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        if text == value:
            return f"{{{{{key}}}}}"
    if text == "demo":
        return "{{operator_password}}"
    return text
