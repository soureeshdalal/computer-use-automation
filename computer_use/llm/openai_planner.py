"""OpenAI-backed planner for discovery."""

from __future__ import annotations

import json
from typing import Any, Protocol

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field

from computer_use.surfaces.playwright_surface import PageObservation


class PlannedAction(BaseModel):
    action: str = Field(description="One of click, type, extract, done, escalate")
    element_id: str | None = None
    text: str | None = None
    output_name: str | None = None
    reason: str = ""


class Planner(Protocol):
    def plan(self, goal: str, observation: PageObservation, step: int) -> PlannedAction:
        ...


SYSTEM_PROMPT = """You operate a legacy credit union back-office UI.
Choose exactly one next action based on the observation.
Use element ids from the observation (e1, e2, ...).
Actions:
- click: press a button or link
- type: enter text into an input (set text)
- extract: read a visible value into output_name when the goal is satisfied
- done: goal appears complete and checkpoint text is visible
- escalate: blocked by dialog or unknown state

Respond as JSON with keys: action, element_id, text, output_name, reason.
Never invent element ids. Prefer minimal steps. Sign in with password demo when needed.
"""


class OpenAIPlanner:
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self.client = ChatOpenAI(model=model, api_key=api_key, temperature=0)
        self.call_count = 0

    def plan(self, goal: str, observation: PageObservation, step: int) -> PlannedAction:
        payload = {
            "goal": goal,
            "step": step,
            "url": observation.url,
            "title": observation.title,
            "dialog": observation.dialog_text,
            "text_excerpt": observation.visible_text_excerpt,
            "elements": [
                {
                    "id": element.element_id,
                    "role": element.role,
                    "name": element.name,
                    "tag": element.tag,
                    "input_type": element.input_type,
                    "value": element.value,
                }
                for element in observation.elements
            ],
        }
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=json.dumps(payload, indent=2)),
        ]
        response = self.client.invoke(messages)
        self.call_count += 1
        content = _extract_json(str(response.content))
        return PlannedAction.model_validate(content)


class MockPlanner:
    """Deterministic planner for offline smoke tests."""

    def __init__(self) -> None:
        self.call_count = 0
        self._login_clicks = 0
        self._member_typed = False
        self._extracted = False

    def plan(self, goal: str, observation: PageObservation, step: int) -> PlannedAction:
        self.call_count += 1
        text = observation.visible_text_excerpt
        url = observation.url

        if "login" in url:
            if step == 1:
                return PlannedAction(action="type", element_id="e1", text="ops001", reason="operator id")
            if step == 2:
                return PlannedAction(action="type", element_id="e2", text="demo", reason="password")
            return PlannedAction(action="click", element_id="e3", reason="sign in")

        if "Member Details" in text:
            if self._extracted:
                return PlannedAction(action="done", reason="complete")
            self._extracted = True
            return PlannedAction(
                action="extract",
                element_id="e1",
                output_name="savings_balance",
                reason="read balance",
            )

        if "Member Lookup" in text or "/home" in url:
            member_id = _extract_member_id(goal)
            if not self._member_typed:
                self._member_typed = True
                return PlannedAction(action="type", element_id="e1", text=member_id, reason="member id")
            return PlannedAction(action="click", element_id="e2", reason="search")

        return PlannedAction(action="done", reason="unexpected page")


def _extract_member_id(goal: str) -> str:
    if "member_id=" in goal:
        return goal.split("member_id=")[-1].strip()
    return "12345"


def _extract_json(content: str) -> dict[str, Any]:
    content = content.strip()
    if content.startswith("```"):
        content = content.strip("`")
        if content.startswith("json"):
            content = content[4:]
    start = content.find("{")
    end = content.rfind("}")
    if start == -1 or end == -1:
        raise ValueError(f"Planner returned non-JSON content: {content}")
    return json.loads(content[start : end + 1])
