"""Deterministic replay engine."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from computer_use.escalation.handoff import HandoffController, HandoffMode
from computer_use.models import (
    ArtifactAction,
    CapabilityArtifact,
    FailureDetail,
    RunResult,
    RunStatus,
)
from computer_use.observability.logger import RunLogger
from computer_use.replay.outcomes import detect_business_outcome
from computer_use.safety.policy import PolicyEngine, PolicyViolation
from computer_use.surfaces.playwright_surface import PlaywrightSurface


class ReplayEngine:
    def __init__(
        self,
        surface: PlaywrightSurface,
        policy: PolicyEngine,
        logger: RunLogger,
        handoff: HandoffController | None = None,
    ) -> None:
        self.surface = surface
        self.policy = policy
        self.logger = logger
        self.handoff = handoff or HandoffController(mode=HandoffMode.AUTO)

    def run(
        self,
        artifact: CapabilityArtifact,
        input_values: dict[str, str],
    ) -> RunResult:
        start = time.time()
        recovered: list[str] = []
        outputs: dict[str, Any] = {}

        self.surface.start()
        try:
            entry = _render_template(artifact.target.entry_url, input_values)
            self.policy.check_url(entry)
            self.surface.navigate(entry)

            for step in artifact.steps:
                page_text = self._page_text()
                business = detect_business_outcome(page_text)
                if business:
                    return self._business_result(
                        artifact, business, start, recovered
                    )

                if self._blocking_dialog():
                    handled = self._handle_dialog(step.id, artifact, input_values, recovered)
                    if handled:
                        continue
                    return self._failure(
                        artifact,
                        step.id,
                        "UNRECOVERABLE_DIALOG",
                        "Blocking dialog requires human intervention.",
                        expected="No blocking dialog",
                        observed=self._page_text()[:300],
                        start=start,
                        recovered=recovered,
                    )

                rendered_value = (
                    _render_template(step.value_template, input_values)
                    if step.value_template
                    else None
                )

                for attempt in range(self.policy.max_retries + 1):
                    try:
                        self._execute_step(step, rendered_value, outputs)
                        break
                    except PolicyViolation as exc:
                        return self._failure(
                            artifact,
                            step.id,
                            exc.code,
                            exc.message,
                            expected="Policy-compliant action",
                            observed=exc.message,
                            start=start,
                            recovered=recovered,
                        )
                    except Exception as exc:  # noqa: BLE001
                        if attempt >= self.policy.max_retries:
                            return self._failure(
                                artifact,
                                step.id,
                                "STEP_FAILED",
                                str(exc),
                                expected=f"Step {step.action.value} succeeds",
                                observed=str(exc),
                                start=start,
                                recovered=recovered,
                            )
                        recovered.append(f"retry_step_{step.id}_attempt_{attempt+1}")

            if not self.surface.page_contains(artifact.success_checkpoint):
                return self._failure(
                    artifact,
                    "checkpoint",
                    "CHECKPOINT_FAILED",
                    "Success checkpoint not found after replay.",
                    expected=artifact.success_checkpoint,
                    observed=self._page_text()[:300],
                    start=start,
                    recovered=recovered,
                )

            duration_ms = int((time.time() - start) * 1000)
            trace_path = str(self.logger.trace_path())
            self.surface.stop(trace_path=trace_path)
            result = RunResult(
                status=RunStatus.SUCCESS,
                capability_name=artifact.name,
                run_id=self.logger.run_id,
                llm_calls=0,
                outputs=outputs,
                recovered_conditions=recovered,
                evidence_dir=str(self.logger.run_dir),
                duration_ms=duration_ms,
            )
            self.logger.write_summary(result.model_dump())
            return result
        except Exception as exc:  # noqa: BLE001
            screenshot = self.logger.screenshot_path("failure")
            try:
                self.surface.screenshot(str(screenshot))
            except Exception:
                pass
            self.surface.stop(trace_path=str(self.logger.trace_path()))
            return RunResult(
                status=RunStatus.FAILURE,
                capability_name=artifact.name,
                run_id=self.logger.run_id,
                llm_calls=0,
                failure=FailureDetail(
                    code="REPLAY_EXCEPTION",
                    message=str(exc),
                    evidence_path=str(screenshot),
                ),
                recovered_conditions=recovered,
                evidence_dir=str(self.logger.run_dir),
                duration_ms=int((time.time() - start) * 1000),
            )

    def _execute_step(
        self,
        step,
        rendered_value: str | None,
        outputs: dict[str, Any],
    ) -> None:
        self.policy.check_action(step.action.value)
        if step.action == ArtifactAction.CLICK:
            self.surface.click_locator(step.targets)
        elif step.action == ArtifactAction.TYPE:
            if rendered_value is None:
                raise ValueError(f"Step {step.id} missing input value")
            self.surface.type_locator(step.targets, rendered_value)
        elif step.action == ArtifactAction.EXTRACT:
            handle = self.surface.resolve_locator(step.targets)
            value = handle.inner_text(timeout=self.policy.step_timeout_ms).strip()
            if step.output_name:
                outputs[step.output_name] = value
        elif step.action == ArtifactAction.NAVIGATE:
            if rendered_value:
                self.policy.check_url(rendered_value)
                self.surface.navigate(rendered_value)
        else:
            raise ValueError(f"Unsupported action {step.action}")

        self.logger.log(
            "replay_step",
            {"step_id": step.id, "action": step.action.value, "value": rendered_value},
        )

    def _blocking_dialog(self) -> bool:
        observation = self.surface.observe()
        return bool(observation.dialog_text)

    def _handle_dialog(
        self,
        step_id: str | None,
        artifact: CapabilityArtifact,
        input_values: dict[str, str],
        recovered: list[str],
    ) -> bool:
        pre = self.logger.screenshot_path("pre_handoff")
        self.surface.screenshot(str(pre))

        if self.handoff.mode == HandoffMode.INTERACTIVE:
            resumed = self.handoff.request_intervention(
                capability_name=artifact.name,
                goal=_render_template(artifact.goal_template, input_values),
                step_id=step_id,
                reason="Blocking session dialog detected",
                url=self.surface.current_url(),
                screenshot_path=str(pre),
            )
            if not resumed:
                return False
            post = self.logger.screenshot_path("post_handoff")
            self.surface.screenshot(str(post))
            recovered.append("human_handoff_completed")
            return True

        assert self.surface.page is not None
        try:
            self.surface.page.get_by_role(
                "button", name="Acknowledge and Continue"
            ).click(timeout=self.policy.step_timeout_ms)
            recovered.append("auto_ack_dialog")
            return True
        except Exception:
            return False

    def _page_text(self) -> str:
        assert self.surface.page is not None
        return self.surface.page.locator("body").inner_text(timeout=5000)

    def _business_result(
        self,
        artifact: CapabilityArtifact,
        business,
        start: float,
        recovered: list[str],
    ) -> RunResult:
        self.surface.stop(trace_path=str(self.logger.trace_path()))
        result = RunResult(
            status=RunStatus.BUSINESS_OUTCOME,
            capability_name=artifact.name,
            run_id=self.logger.run_id,
            llm_calls=0,
            business_outcome=business,
            recovered_conditions=recovered,
            evidence_dir=str(self.logger.run_dir),
            duration_ms=int((time.time() - start) * 1000),
        )
        self.logger.write_summary(result.model_dump())
        return result

    def _failure(
        self,
        artifact: CapabilityArtifact,
        step_id: str | None,
        code: str,
        message: str,
        expected: str,
        observed: str,
        start: float,
        recovered: list[str],
    ) -> RunResult:
        screenshot = self.logger.screenshot_path("failure")
        try:
            self.surface.screenshot(str(screenshot))
        except Exception:
            pass
        self.surface.stop(trace_path=str(self.logger.trace_path()))
        result = RunResult(
            status=RunStatus.FAILURE,
            capability_name=artifact.name,
            run_id=self.logger.run_id,
            llm_calls=0,
            failure=FailureDetail(
                code=code,
                message=message,
                step_id=step_id,
                expected=expected,
                observed=observed,
                evidence_path=str(screenshot),
            ),
            recovered_conditions=recovered,
            evidence_dir=str(self.logger.run_dir),
            duration_ms=int((time.time() - start) * 1000),
        )
        self.logger.write_summary(result.model_dump())
        return result


def _render_template(template: str | None, values: dict[str, str]) -> str:
    if not template:
        return ""
    result = template
    for key, value in values.items():
        result = result.replace(f"{{{{{key}}}}}", value)
    return result
