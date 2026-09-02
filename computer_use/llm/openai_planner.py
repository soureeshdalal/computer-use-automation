"""OpenAI-backed planner for discovery."""

from __future__ import annotations

import json
from typing import Any, Protocol

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
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


SYSTEM_PROMPT = """You operate a legacy credit union member servicing console.

Workflow:
1) Login page (/login): type password "demo" into Password field, click Sign In.
2) Member Lookup page (/home): type the member number into Member Number field ONCE, then click "Search Member Records". Never type the password on this page.
3) Member Details page: use action "extract" with output_name "savings_balance" to read the savings balance, then action "done".

Rules:
- Use only element ids from the observation (e1, e2, ...).
- After typing a value, the next step on the same page should usually be a click on the submit/search button.
- Do not repeat the same type action on the same field unless the page reloaded.
- Actions: click, type, extract, done, escalate.

Respond with JSON only: {"action","element_id","text","output_name","reason"}
"""


class OpenAIPlanner:
    def __init__(self, model: str, api_key: str) -> None:
        self.model = model
        self.client = ChatOpenAI(model=model, api_key=api_key, temperature=0)
        self.call_count = 0
        self._history: list = [SystemMessage(content=SYSTEM_PROMPT)]

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
        user_message = HumanMessage(content=json.dumps(payload, indent=2))
        messages = self._history + [user_message]
        response = self.client.invoke(messages)
        self.call_count += 1
        content = _extract_json(str(response.content))
        planned = PlannedAction.model_validate(content)
        self._history.extend([user_message, AIMessage(content=json.dumps(planned.model_dump()))])
        return planned


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
        lines = content.splitlines()
        lines = lines[1:]
        if lines and lines[0].strip().lower() == "json":
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        content = "\n".join(lines).strip()
    start = content.find("{")
    if start == -1:
        raise ValueError(f"Planner returned non-JSON content: {content}")
    decoder = json.JSONDecoder()
    parsed, _ = decoder.raw_decode(content[start:])
    return parsed
